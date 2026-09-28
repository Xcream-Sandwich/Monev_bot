import json
import logging
import random
from typing import TypedDict, Any
import config
from storage import load_templates

logger = logging.getLogger(__name__)

# Minimum character requirement per section
MIN_SECTION_LEN = 100

# Built-in generic fallback template if templates.json is missing or empty
BUILTIN_FALLBACK_TEMPLATE = {
    "aktivitas": "Melaksanakan tugas harian magang sesuai dengan rencana kerja dan target yang telah ditentukan oleh pembimbing, melakukan koordinasi teknis serta meninjau kembali kode dan fungsionalitas sistem.",
    "pembelajaran": "Mempelajari alur penyelesaian masalah pada sistem perangkat lunak, memahami pentingnya penulisan kode yang rapi serta penerapan praktik terbaik dalam pengembangan aplikasi secara kolaboratif.",
    "kendala": "Tidak ada kendala yang menghambat jalannya pengerjaan hari ini, seluruh aktivitas teknis dan alur komunikasi tim berjalan dengan lancar dan sesuai target.",
}

# Contextual padding sentences to guarantee >= 100 characters
PADDING_AKTIVITAS = [
    " Seluruh rangkaian kegiatan harian ini diselesaikan secara terstruktur sesuai dengan target kerja yang telah ditetapkan.",
    " Selain itu, dilakukan peninjauan kembali terhadap hasil pekerjaan untuk memastikan kesesuaian dengan standar teknis magang.",
    " Aktivitas diakhiri dengan dokumentasi ringkas mengenai progres harian agar mudah ditindaklanjuti pada hari kerja berikutnya.",
]

PADDING_PEMBELAJARAN = [
    " Proses ini menambah wawasan berharga terkait alur kerja profesional, pemecahan masalah teknis, serta peningkatan efisiensi tugas.",
    " Pembelajaran ini membantu memperdalam pemahaman mengenai implementasi best practice dalam lingkungan pengembangan modern.",
    " Pengalaman hari ini memberikan gambaran yang lebih komprehensif mengenai kolaborasi tim dan tata kelola pekerjaan teknis.",
]

PADDING_KENDALA = [
    " Tidak terdapat kendala kritis yang menghambat pekerjaan hari ini; semua tantangan teknis dapat diselesaikan melalui koordinasi yang baik.",
    " Segala kendala kecil yang muncul berhasil diatasi dengan baik melalui eksplorasi dokumentasi dan komunikasi bersama rekan tim.",
    " Seluruh alur pekerjaan dapat berjalan dengan kondusif tanpa kendala operasional yang berarti.",
]


class ReportData(TypedDict):
    aktivitas: str
    pembelajaran: str
    kendala: str
    source: str


def pad_to_min_length(text: str, padding_list: list[str], min_length: int = MIN_SECTION_LEN) -> str:
    """Pad text with contextual sentences until it meets min_length."""
    text = (text or "").strip()
    idx = 0
    while len(text) < min_length:
        text += padding_list[idx % len(padding_list)]
        idx += 1
    return text.strip()


def validate_and_pad_report(report: dict, source_label: str) -> ReportData:
    """Ensure all 3 sections exist and meet the 100-character requirement."""
    akt = pad_to_min_length(report.get("aktivitas", ""), PADDING_AKTIVITAS)
    pem = pad_to_min_length(report.get("pembelajaran", ""), PADDING_PEMBELAJARAN)
    ken = pad_to_min_length(report.get("kendala", ""), PADDING_KENDALA)
    
    return {
        "aktivitas": akt,
        "pembelajaran": pem,
        "kendala": ken,
        "source": source_label,
    }


def generate_from_points_local(points: list[str]) -> dict:
    """Generate 3 sections from points locally without AI."""
    cleaned_points = [p.strip() for p in points if p.strip()]
    if not cleaned_points:
        return BUILTIN_FALLBACK_TEMPLATE.copy()
    
    points_joined = "; ".join(cleaned_points)
    aktivitas = f"Pada hari ini, aktivitas magang yang dilakukan meliputi: {points_joined}."
    
    first_point = cleaned_points[0]
    pembelajaran = f"Dari rangkaian kegiatan hari ini, diperoleh pemahaman mendalam terkait proses teknis dan alur implementasi {first_point}."
    kendala = "Tidak ada kendala kritis yang menghambat pelaksanaan tugas hari ini; proses pengerjaan berjalan dengan baik dan lancar."
    
    return {
        "aktivitas": aktivitas,
        "pembelajaran": pembelajaran,
        "kendala": kendala,
    }


async def generate_from_points_groq(points: list[str]) -> dict | None:
    """Generate 3 sections from points using Groq LLM (llama-3.3-70b-versatile)."""
    if not config.GROQ_API_KEY:
        return None
    
    try:
        from groq import AsyncGroq
        client = AsyncGroq(api_key=config.GROQ_API_KEY)
        
        prompt = (
            "Berikut adalah poin-poin aktivitas magang peserta hari ini:\n"
            + "\n".join(f"- {p}" for p in points)
            + "\n\n"
            "Tolong susun laporan harian presensi magang dalam format JSON dengan 3 kunci persis: "
            "'aktivitas', 'pembelajaran', 'kendala'.\n"
            "Ketentuan:\n"
            "1. Bahasa Indonesia baku dan profesional.\n"
            "2. 'aktivitas' merangkum apa yang dikerjakan secara jelas.\n"
            "3. 'pembelajaran' menjabarkan insight teknis atau softskill yang dipelajari dari poin di atas.\n"
            "4. 'kendala' mendeskripsikan kendala yang dialami dan solusinya (atau sebutkan tidak ada kendala jika lancar).\n"
            "5. Setiap bagian WAJIB memiliki panjang minimal 100 karakter.\n"
            "6. Balas HANYA dengan JSON valid tanpa markdown formatting tambahan atau pembuka/penutup lainnya."
        )
        
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "Kamu adalah asisten penyusun laporan harian magang Kemnaker yang profesional dan akurat. Output selalu berupa JSON murni.",
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.4,
            max_tokens=800,
        )
        
        content = response.choices[0].message.content
        data = json.loads(content)
        
        if "aktivitas" in data and "pembelajaran" in data and "kendala" in data:
            return {
                "aktivitas": str(data["aktivitas"]),
                "pembelajaran": str(data["pembelajaran"]),
                "kendala": str(data["kendala"]),
            }
    except Exception as e:
        logger.warning(f"Gagal memanggil Groq LLM: {e}")
    
    return None


def select_template_from_store(day_name: str | None = None) -> tuple[dict, str]:
    """
    Select template from TEMPLATES_JSON env secret or templates.json based on priority:
    1. Matching English day name (Monday..Sunday)
    2. 'default' key
    3. Built-in generic template
    """
    templates = {}
    if config.TEMPLATES_JSON:
        try:
            parsed = json.loads(config.TEMPLATES_JSON)
            if isinstance(parsed, dict):
                templates = parsed
        except Exception:
            templates = load_templates()
    else:
        templates = load_templates()

    if not day_name:
        day_name = config.get_now_wib().strftime("%A")
    
    day_name_cap = day_name.capitalize()
    
    def is_valid_entry(entry: Any) -> bool:
        if not isinstance(entry, dict):
            return False
        return (
            bool(entry.get("aktivitas", "").strip())
            and bool(entry.get("pembelajaran", "").strip())
            and bool(entry.get("kendala", "").strip())
        )
    
    # Priority 1: Day of week list
    day_list = [e for e in templates.get(day_name_cap, []) if is_valid_entry(e)]
    if day_list:
        return random.choice(day_list), f"template ({day_name_cap})"
    
    # Priority 2: 'default' list
    default_list = [e for e in templates.get("default", []) if is_valid_entry(e)]
    if default_list:
        return random.choice(default_list), "template (default)"
    
    # Priority 3: Built-in fallback
    return BUILTIN_FALLBACK_TEMPLATE.copy(), "template (bawaan)"


async def build_daily_report(points: list[str] | None = None, day_name: str | None = None) -> ReportData:
    """
    Build daily report following PRD rules:
    - If points exist: Groq LLM -> Local generator fallback
    - If no points: template from TEMPLATES_JSON / templates.json -> fallback
    - All sections padded to >= 100 chars
    """
    cleaned_points = [p.strip() for p in (points or []) if p.strip()]
    
    if cleaned_points:
        groq_result = await generate_from_points_groq(cleaned_points)
        if groq_result:
            return validate_and_pad_report(groq_result, "poin (Groq AI)")
        
        local_result = generate_from_points_local(cleaned_points)
        return validate_and_pad_report(local_result, "poin (Lokal)")
    
    tmpl, source_label = select_template_from_store(day_name=day_name)
    return validate_and_pad_report(tmpl, source_label)
