"""
SafeShop AI v2 - backend

What it does
  1. Receives a screenshot of an online product listing (plus optional details).
  2. Asks Google Gemini (free tier) to read the screenshot: brand, product, price,
     MRP, seller, visible text, spelling/logo problems.
  3. Looks up a reference price: Google Search via Gemini (if available),
     otherwise SafeShop's own brand list, otherwise Gemini's own estimate.
  4. Runs clear, rule-based checks (red-flag words, misspelled brands, price,
     seller) and combines them into a risk level with reasons.

Environment variables (set them in Hugging Face > Space > Settings > Secrets)
  GEMINI_API_KEY         required. Free key from https://aistudio.google.com
  GEMINI_MODELS          optional. Comma separated, tried in order.
  ENABLE_SEARCH          optional. "true" (default) or "false".
  ALLOWED_ORIGINS        optional. Your website URL(s), comma separated. Default "*".
  RATE_LIMIT_PER_MINUTE  optional. Checks per visitor per minute. Default 6.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image

# ── Config ────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("safeshop")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODELS = [
    m.strip()
    for m in os.environ.get("GEMINI_MODELS", "gemini-2.5-flash,gemini-2.5-flash-lite,gemini-flash-latest").split(",")
    if m.strip()
]
ENABLE_SEARCH = os.environ.get("ENABLE_SEARCH", "true").strip().lower() in ("1", "true", "yes")
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "6"))
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
VERSION = "2.0.0"

Image.MAX_IMAGE_PIXELS = 40_000_000  # protects against giant "decompression bomb" images

DATA_DIR = Path(__file__).parent / "data"
BRANDS: list[dict] = json.loads((DATA_DIR / "brands.json").read_text(encoding="utf-8"))["brands"]
_flags = json.loads((DATA_DIR / "red_flags.json").read_text(encoding="utf-8"))
STRONG_FLAGS: list[str] = _flags["strong"]
MEDIUM_FLAGS: list[str] = _flags["medium"]

CATEGORIES = [
    "footwear", "apparel", "watch", "eyewear", "bag", "perfume", "cosmetics", "electronics",
    "mobile_accessory", "food", "personal_care", "home", "toy", "sports", "other",
]

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="SafeShop AI", version=VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class BadInput(Exception):
    pass


class AIError(Exception):
    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"ok": False, "error": code, "message": message})


# ── Rate limiting (simple, in memory, per visitor IP) ─────────────────────────
_hits: dict[str, deque] = defaultdict(deque)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def is_rate_limited(ip: str) -> bool:
    now = time.time()
    q = _hits[ip]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_LIMIT_PER_MINUTE:
        return True
    q.append(now)
    return False


# ── Helpers ───────────────────────────────────────────────────────────────────
def norm(text: Optional[str]) -> str:
    """lowercase, letters/digits only, single spaces"""
    t = (text or "").lower().replace("'", "")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def to_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    m = re.search(r"\d[\d,]*(?:\.\d+)?", str(value))
    if not m:
        return None
    try:
        n = float(m.group(0).replace(",", ""))
    except ValueError:
        return None
    return n if n > 0 else None


def rupees(n: Optional[float]) -> str:
    if n is None:
        return "unknown"
    n = round(n)
    s = str(int(n))
    if len(s) > 3:  # Indian grouping: 1,23,456
        head, tail = s[:-3], s[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        s = f"{head},{tail}"
    return f"₹{s}"


def prepare_image(raw: bytes) -> bytes:
    if not raw:
        raise BadInput("The image is empty. Upload a screenshot of the listing.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise BadInput("The image is larger than 8 MB. Upload a smaller screenshot.")
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception:
        raise BadInput("That file isn't an image we can read. Upload a JPG, PNG or WEBP screenshot.")
    if img.width < 100 or img.height < 100:
        raise BadInput("The image is too small to read. Upload a clearer screenshot.")
    img = img.convert("RGB")
    img.thumbnail((1600, 1600))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=88)
    return out.getvalue()


def parse_json(text: str) -> dict:
    t = re.sub(r"```(?:json)?", "", text or "").strip()
    try:
        data = json.loads(t)
        if isinstance(data, list) and data:
            data = data[0]
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(t[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise AIError("bad_output", t[:200])


# ── Gemini ────────────────────────────────────────────────────────────────────
def _text_from_response(data: dict) -> str:
    out = []
    for cand in (data.get("candidates") or [])[:1]:
        for part in (cand.get("content") or {}).get("parts") or []:
            if isinstance(part.get("text"), str) and not part.get("thought"):
                out.append(part["text"])
    return "".join(out).strip()


async def call_gemini(parts: list, *, json_mode: bool, use_search: bool = False, timeout: float = 60.0) -> tuple[str, str]:
    """Try each model in GEMINI_MODELS until one answers. Returns (text, model)."""
    if not GEMINI_API_KEY:
        raise AIError("missing_key")
    errors: list[str] = []
    statuses: list[int] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        for model in GEMINI_MODELS:
            config: dict[str, Any] = {"temperature": 0.1}
            if json_mode:
                config["responseMimeType"] = "application/json"
            body: dict[str, Any] = {"contents": [{"role": "user", "parts": parts}], "generationConfig": config}
            if use_search:
                body["tools"] = [{"google_search": {}}]
            try:
                r = await client.post(
                    GEMINI_URL.format(model=model),
                    headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
                    json=body,
                )
            except httpx.HTTPError as e:
                errors.append(f"{model}: {e.__class__.__name__}")
                continue
            statuses.append(r.status_code)
            if r.status_code == 200:
                text = _text_from_response(r.json())
                if text:
                    return text, model
                errors.append(f"{model}: empty answer")
                continue
            detail = r.text[:300]
            errors.append(f"{model}: HTTP {r.status_code} {detail}")
            if r.status_code in (401, 403) or (r.status_code == 400 and "API key" in detail):
                raise AIError("bad_key", detail)
    log.warning("Gemini failed: %s", " | ".join(errors))
    if statuses and all(s == 429 for s in statuses):
        raise AIError("busy", " | ".join(errors))
    raise AIError("unavailable", " | ".join(errors))


EXTRACT_PROMPT = """You are SafeShop AI, helping Indian online shoppers spot counterfeit listings.
Look carefully at this screenshot of a product listing (Meesho, Flipkart, Amazon, Instagram, WhatsApp, etc.).
{user_context}
Read everything visible and return ONLY a JSON object with exactly these keys:
{{
  "is_product_listing": true/false,     // false if this is not a product or product listing at all
  "product_name": string or null,       // e.g. "Nike Air Force 1 sneakers"
  "brand": string or null,              // the brand the listing claims, spelled as the real brand
  "category": one of {categories},
  "pack_size": string or null,          // e.g. "52 g", "100 ml", "UK 9", "pack of 2"
  "listed_price_inr": number or null,   // the price the buyer pays now
  "mrp_inr": number or null,            // struck-through MRP if shown
  "discount_percent": number or null,
  "platform": string or null,           // Meesho, Flipkart, Amazon, Instagram ... if recognisable
  "seller_name": string or null,
  "seller_rating": number or null,      // out of 5
  "rating_count": number or null,       // number of ratings/reviews
  "visible_text": string,               // the title and key listing text you can read, max 400 chars
  "brand_spelling_ok": true/false/null, // false if the brand name or logo on the product/title is misspelled or altered (e.g. "Adibas", "Nlke")
  "brand_spelling_issue": string or null,
  "logo_concerns": [strings],           // visible problems with logo/branding; empty if none
  "packaging_concerns": [strings],      // visible problems: poor print, missing MRP/labels, wrong fonts, blurry stock photo; empty if none
  "red_flag_phrases_seen": [strings],   // exact phrases like "first copy", "7A quality", "replica", "inspired by"
  "typical_genuine_price_inr": number or null, // your best estimate of the normal Indian price of the GENUINE item in this size, null if unsure
  "ai_suspicion": number,               // 0-100, how likely this listing is selling a counterfeit
  "ai_summary": string                  // 1-2 short plain sentences for the shopper
}}
Be factual. Do not guess prices you cannot see; use null. Genuine brands are often discounted 10-50%, that alone is not suspicious."""


async def extract_listing(image_jpeg: bytes, name: str, description: str, price: Optional[float]) -> tuple[dict, str]:
    context_lines = []
    if name:
        context_lines.append(f"The shopper says the product is: {name[:150]}")
    if price:
        context_lines.append(f"The shopper says the listed price is: ₹{price:g}")
    if description:
        context_lines.append(f"Listing description pasted by the shopper: {description[:1500]}")
    user_context = ("\n".join(context_lines) + "\n") if context_lines else ""
    prompt = EXTRACT_PROMPT.format(user_context=user_context, categories=json.dumps(CATEGORIES))
    parts = [
        {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(image_jpeg).decode()}},
        {"text": prompt},
    ]
    text, model = await call_gemini(parts, json_mode=True)
    return parse_json(text), model


async def search_reference_price(brand: str, product: str, pack_size: str) -> Optional[float]:
    """Ask Gemini with Google Search for the usual Indian price. Returns None if unavailable."""
    if not ENABLE_SEARCH or not (brand or product):
        return None
    query = " ".join(x for x in [brand, product, pack_size] if x)
    prompt = (
        f"Search the web for the current usual selling price in India of the GENUINE product: {query}. "
        "Use official brand stores or large retailers. "
        'Reply with ONLY a JSON object: {"price_inr": number or null, "note": "short source note"}'
    )
    try:
        text, _ = await call_gemini([{"text": prompt}], json_mode=False, use_search=True, timeout=30.0)
        value = to_number(parse_json(text).get("price_inr"))
        if value and 1 <= value <= 10_000_000:
            return value
    except Exception as e:  # search is a bonus; never break the check because of it
        log.info("Price search skipped: %s", e)
    return None


# ── Rule checks ───────────────────────────────────────────────────────────────
def find_brand_entry(brand: str, product: str, category: str) -> Optional[dict]:
    hay = f" {norm(brand)} {norm(product)} "
    prod = f" {norm(product)} "
    best: Optional[tuple[int, dict]] = None
    for entry in BRANDS:
        names = [norm(n) for n in [entry["brand"], *entry.get("aliases", [])]]
        if not any(n and f" {n} " in hay for n in names):
            continue
        keywords = entry.get("keywords") or []
        if keywords:
            if not any(f" {norm(k)} " in prod for k in keywords):
                continue
            score = 2
        else:
            if category and entry.get("category") and category != entry["category"]:
                continue
            score = 1
        # prefer keyword matches, then the more specific (pricier) line, e.g. Air Jordan over Nike
        if best is None or (score, entry["min_genuine_inr"]) > (best[0], best[1]["min_genuine_inr"]):
            best = (score, entry)
    return best[1] if best else None


def find_lookalikes(text: str) -> list[str]:
    hay = f" {norm(text)} "
    hits = []
    for entry in BRANDS:
        for fake in entry.get("lookalikes", []):
            if f" {norm(fake)} " in hay:
                hits.append(f"“{fake}” instead of “{entry['brand'].title()}”")
    return sorted(set(hits))


def find_flag_phrases(text: str, phrases: list[str]) -> list[str]:
    low = re.sub(r"\s+", " ", (text or "").lower())
    found = []
    for phrase in phrases:
        pattern = r"(?<![a-z0-9])" + re.escape(phrase.lower()) + r"(?![a-z0-9])"
        for m in re.finditer(pattern, low):
            before = low[max(0, m.start() - 12) : m.start()]
            if re.search(r"\b(no|not|never|zero|koi)\s+(a\s+|an\s+)?$", before):
                continue  # "not a first copy", "no duplicate"
            found.append(phrase)
            break
    # drop phrases contained in longer found ones ("copy" inside "first copy")
    return [p for p in found if not any(p != q and p in q for q in found)]


CATEGORY_TIPS = {
    "footwear": ["Check the size label inside the tongue and the box label: the style code on both should match.",
                 "Prefer the brand's own store on Flipkart/Amazon/Myntra, or the brand's website."],
    "apparel": ["Look at close-up photos of the brand tag and stitching; fakes often have uneven logos.",
                "Check whether the seller is listed as the brand or an authorised retailer."],
    "watch": ["Luxury watches are almost never sold on Meesho or Instagram at big discounts.",
              "Ask for the serial number and warranty card, and verify them with the brand."],
    "eyewear": ["Genuine sunglasses have the brand and model number printed on the inside of the temple arm."],
    "bag": ["Designer bags sold for a few thousand rupees are almost always copies.",
            "Look for even stitching, straight logo patterns and a proper serial/date code."],
    "perfume": ["Check for a batch code printed on both the bottle and the box, and that they match.",
                "“Inspired by” perfumes are not the brand; they only imitate the smell."],
    "cosmetics": ["Check for batch number, expiry date and importer/manufacturer details on the pack.",
                  "Fake cosmetics can harm skin; buy from the brand store or authorised sellers."],
    "electronics": ["Verify the serial or IMEI number on the brand's official website after delivery.",
                    "Check that the listing includes a brand warranty, not just a “seller warranty”."],
    "mobile_accessory": ["Fake chargers and cables can overheat. Buy from the brand store or authorised sellers."],
    "food": ["Check the FSSAI licence number, MRP, and manufacturing and expiry dates on the pack."],
    "personal_care": ["Check for batch number, MRP, expiry date and manufacturer address on the pack."],
}
GENERAL_TIPS = [
    "Prefer Cash on Delivery or an open-box delivery for expensive items so you can inspect first.",
    "Read the lowest-rated reviews; buyers usually mention “fake” or “duplicate” there first.",
]


def build_report(ai: dict, user_price: Optional[float], user_text: str, search_price: Optional[float], model: str) -> dict:
    brand = (ai.get("brand") or "").strip()
    product = (ai.get("product_name") or "").strip()
    category = ai.get("category") if ai.get("category") in CATEGORIES else "other"
    pack_size = (ai.get("pack_size") or "").strip()
    price = user_price or to_number(ai.get("listed_price_inr"))
    mrp = to_number(ai.get("mrp_inr"))
    discount = to_number(ai.get("discount_percent"))
    if discount is None and price and mrp and mrp > price:
        discount = round((1 - price / mrp) * 100)
    seller_rating = to_number(ai.get("seller_rating"))
    rating_count = ai.get("rating_count")
    rating_count = int(to_number(rating_count)) if to_number(rating_count) else None
    ai_suspicion = max(0.0, min(100.0, to_number(ai.get("ai_suspicion")) or 0.0))

    entry = find_brand_entry(brand, product, category)
    premium = bool(entry and entry.get("premium"))
    all_text = " ".join(
        str(x) for x in [product, brand, ai.get("visible_text") or "", user_text,
                         " ".join(ai.get("red_flag_phrases_seen") or [])]
    )

    signals: list[dict] = []
    points = 0
    strong_signal = False

    def add(severity: str, title: str, detail: str, pts: int = 0):
        nonlocal points
        signals.append({"severity": severity, "title": title, "detail": detail})
        points += pts

    # 1. Red-flag words
    strong = find_flag_phrases(all_text, STRONG_FLAGS)
    medium = [p for p in find_flag_phrases(all_text, MEDIUM_FLAGS) if p not in strong]
    if strong:
        strong_signal = True
        add("high", "Listing uses words that mean “copy”",
            "Found: " + ", ".join(f"“{p}”" for p in strong[:5]) + ". Genuine sellers don't describe products this way.", 55)
    if medium:
        add("medium", "Wording often used for non-original goods",
            "Found: " + ", ".join(f"“{p}”" for p in medium[:5]) + ".", 18)

    # 2. Brand spelling
    lookalikes = find_lookalikes(all_text)
    if lookalikes:
        strong_signal = True
        add("high", "Brand name is misspelled", "Found " + "; ".join(lookalikes[:3]) + ". This is a classic counterfeit trick.", 45)
    elif ai.get("brand_spelling_ok") is False and brand:
        strong_signal = True
        issue = ai.get("brand_spelling_issue") or "The brand name or logo looks altered."
        add("high", "Brand name or logo looks altered", str(issue)[:200], 40)

    # 3. Price
    reference, ref_source = None, None
    if search_price:
        reference, ref_source = search_price, "web search"
    elif to_number(ai.get("typical_genuine_price_inr")):
        reference, ref_source = to_number(ai.get("typical_genuine_price_inr")), "AI estimate"

    price_points, price_signal = 0, None
    if price is None:
        add("info", "No price found", "We couldn't read a price. Add it under “Add details” for a better check.")
    else:
        if entry:
            floor = float(entry["min_genuine_inr"])
            if price < floor * 0.5:
                price_points = 40
                if premium:
                    strong_signal = True  # e.g. a "Rolex" for ₹2,999
                price_signal = ("high", "Price is far too low for this brand",
                                f"{rupees(price)} is less than half of what genuine {entry['brand'].title()} items usually cost (from about {rupees(floor)}).")
            elif price < floor:
                price_points = 22
                price_signal = ("medium", "Price is lower than genuine items usually cost",
                                f"Genuine {entry['brand'].title()} items usually start around {rupees(floor)}; this is {rupees(price)}.")
        if reference:
            ratio = price / reference
            if ratio < 0.25 and price_points < 40:
                price_points = 40
                if premium:
                    strong_signal = True
                price_signal = ("high", "Price is far below the usual price",
                                f"{rupees(price)} vs about {rupees(reference)} usually ({ref_source}). That's {round((1 - ratio) * 100)}% less.")
            elif ratio < 0.45 and price_points < 25:
                price_points = 25
                price_signal = ("medium", "Price is much lower than usual",
                                f"{rupees(price)} vs about {rupees(reference)} usually ({ref_source}).")
            elif ratio < 0.65 and premium and price_points < 10:
                price_points = 10
                price_signal = ("low", "Price is lower than usual for a premium brand",
                                f"{rupees(price)} vs about {rupees(reference)} usually ({ref_source}).")
            elif ratio > 2.5 and price_points == 0:
                price_points = 10
                price_signal = ("low", "Price is much higher than usual",
                                f"{rupees(price)} vs about {rupees(reference)} usually ({ref_source}). You may be overpaying.")
        if price_signal:
            add(*price_signal, price_points)
        elif reference or entry:
            add("good", "Price looks normal", f"{rupees(price)} is in the usual range for this product.")

    if discount and discount >= 80 and premium:
        add("medium", f"{int(discount)}% discount is unusual for this brand",
            "Premium brands rarely sell at such deep discounts, even during sales.", 15)

    # 4. Seller
    if seller_rating is not None and seller_rating < 3.5:
        add("medium", "Seller has a low rating", f"Seller rating is {seller_rating:g}/5.", 10)
    if rating_count is not None and rating_count < 10:
        add("low", "Very few ratings", f"Only {rating_count} ratings, so there's little buyer feedback yet.", 5)

    # 5. What the AI saw in the image
    concerns = [str(c) for c in (ai.get("logo_concerns") or []) + (ai.get("packaging_concerns") or []) if c][:4]
    if concerns:
        add("medium", "Visual problems in the photo", "; ".join(concerns)[:300], min(25, 10 * len(concerns)))

    if not strong and not medium:
        add("good", "No copy-related words found", "The listing text doesn't use words like “first copy” or “replica”.")

    # ── Combine ──
    rule_score = min(100, points)
    risk = round(0.65 * rule_score + 0.35 * ai_suspicion)
    if strong_signal:
        risk = max(risk, 72)
    risk = max(0, min(100, risk))
    if risk >= 65:
        level, verdict = "high", "Likely fake"
    elif risk >= 35:
        level, verdict = "medium", "Be careful"
    else:
        level, verdict = "low", "Looks okay"

    known = bool(price and (reference or entry))
    confidence = "good" if known and brand else "limited"

    order = {"high": 0, "medium": 1, "low": 2, "info": 3, "good": 4}
    signals.sort(key=lambda s: order.get(s["severity"], 5))

    return {
        "ok": True,
        "level": level,
        "verdict": verdict,
        "risk_score": risk,
        "confidence": confidence,
        "summary": (ai.get("ai_summary") or "")[:400],
        "signals": signals,
        "extracted": {
            "product_name": product or None,
            "brand": brand or None,
            "category": category,
            "pack_size": pack_size or None,
            "listed_price": price,
            "mrp": mrp,
            "discount_percent": discount,
            "platform": ai.get("platform"),
            "seller_name": ai.get("seller_name"),
            "seller_rating": seller_rating,
            "rating_count": rating_count,
        },
        "reference_price": {"value": reference, "source": ref_source} if reference else None,
        "brand_floor": {"brand": entry["brand"], "min_genuine_inr": entry["min_genuine_inr"]} if entry else None,
        "tips": (CATEGORY_TIPS.get(category, []) + GENERAL_TIPS)[:4],
        "model": model,
        "disclaimer": "SafeShop AI estimates risk from the screenshot only. It can't prove a product is genuine or fake.",
    }


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return {"service": "SafeShop AI", "version": VERSION, "status": "running", "docs": "/docs"}


@app.get("/health")
async def health():
    return {
        "ok": True,
        "version": VERSION,
        "ai_configured": bool(GEMINI_API_KEY),
        "models": GEMINI_MODELS,
        "search_enabled": ENABLE_SEARCH,
        "brands_loaded": len(BRANDS),
    }


@app.post("/analyze")
async def analyze(
    request: Request,
    image: UploadFile = File(...),
    product_name: str = Form(""),
    description: str = Form(""),
    entered_price: str = Form(""),
):
    if is_rate_limited(client_ip(request)):
        return error(429, "rate_limited", "Too many checks in a minute. Wait a moment and try again.")

    user_price = None
    if entered_price.strip():
        try:
            user_price = float(entered_price.strip().replace(",", "").replace("₹", ""))
        except ValueError:
            user_price = None
        if user_price is None or not (0 < user_price <= 10_000_000):
            return error(400, "bad_price", "Enter the price as a number above 0, for example 499.")

    try:
        image_jpeg = prepare_image(await image.read(MAX_UPLOAD_BYTES + 1))
    except BadInput as e:
        return error(400, "bad_image", str(e))

    name = product_name.strip()[:150]
    desc = "" if description.strip().lower() == "no description provided" else description.strip()[:3000]

    try:
        ai, model = await extract_listing(image_jpeg, name, desc, user_price)
    except AIError as e:
        log.error("Extraction failed: %s", e)
        messages = {
            "missing_key": "The checker isn't set up yet: the GEMINI_API_KEY secret is missing on the server.",
            "bad_key": "The checker's AI key isn't working. The site owner needs to update GEMINI_API_KEY.",
            "busy": "The free AI quota is busy right now. Wait a minute and try again.",
        }
        return error(503, f"ai_{e.kind}", messages.get(e.kind, "The AI service didn't respond. Try again in a minute."))

    if ai.get("is_product_listing") is False:
        return error(422, "not_a_listing",
                     "This doesn't look like a product or product listing. Upload a screenshot of the product page.")

    search_price = await search_reference_price(
        (ai.get("brand") or "").strip(), (ai.get("product_name") or name).strip(), (ai.get("pack_size") or "").strip()
    )
    return build_report(ai, user_price, f"{name} {desc}", search_price, model)
