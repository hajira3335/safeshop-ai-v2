import { scoreListing } from "../_lib/engine.js";
import { extractFromImage, clean, GeminiError } from "../_lib/gemini.js";

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });

const MESSAGES = {
  NO_KEY: "The AI key isn’t set up yet. The site owner needs to add GEMINI_API_KEY. Meanwhile, use the “Type details” tab.",
  BAD_KEY: "The AI key isn’t working. The site owner needs to create a new key. Meanwhile, use the “Type details” tab.",
  QUOTA: "The free AI quota is busy right now. Wait a minute and try again, or use the “Type details” tab.",
  UNAVAILABLE: "The AI service didn’t respond. Try again in a moment, or use the “Type details” tab.",
  BAD_OUTPUT: "We couldn’t read that screenshot clearly. Try a sharper, closer screenshot of the listing.",
};

export async function onRequestPost({ request, env }) {
  let body;
  try { body = await request.json(); } catch { return json({ error: "Invalid request." }, 400); }

  let extracted;
  try {
    if (body.mode === "image") {
      const mime = ["image/jpeg", "image/png", "image/webp"].includes(body.mime) ? body.mime : null;
      if (!mime || typeof body.image !== "string" || body.image.length < 100) return json({ error: "Please upload a JPG, PNG or WebP screenshot." }, 400);
      if (body.image.length > 2_500_000) return json({ error: "That image is too large. Try a smaller screenshot." }, 413);
      extracted = await extractFromImage(env, body.image, mime);
    } else if (body.mode === "text") {
      const price = Number(body.price);
      extracted = clean({
        is_product_listing: true,
        product_name: body.title,
        brand_claimed: body.brand,
        category: body.category,
        price_inr: price > 0 ? price : null,
        seller_name: body.seller,
        platform: body.platform,
        extraction_confidence: "medium",
      });
      extracted.description = String(body.description || "").slice(0, 1500);
    } else {
      return json({ error: "Invalid request." }, 400);
    }
  } catch (e) {
    const code = e instanceof GeminiError ? e.code : "UNAVAILABLE";
    return json({ error: MESSAGES[code] || MESSAGES.UNAVAILABLE, code }, code === "QUOTA" ? 429 : 502);
  }

  if (!extracted.is_product_listing) {
    return json({ notProduct: true, message: "This doesn’t look like a product listing. Please upload a screenshot of a product page." });
  }

  const result = scoreListing(extracted);
  return json({
    ...result,
    extracted: {
      product_name: extracted.product_name, brand: extracted.brand_claimed, price: extracted.price_inr,
      mrp: extracted.mrp_inr, discount: extracted.discount_percent, seller: extracted.seller_name,
      platform: extracted.platform, category: extracted.category,
    },
  });
}
