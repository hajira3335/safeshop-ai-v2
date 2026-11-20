// ============================================================
//  SafeShop AI v2 – scoring engine
//  Risk score starts at 0 and only rises when there is evidence.
//  0-24 Looks genuine | 25-44 Be careful | 45-64 Suspicious
//  65-84 Highly suspicious | 85-100 Likely fake
// ============================================================
import { STRONG_TERMS, WEAK_TERMS, BRANDS, NO_OFFICIAL_PLATFORMS } from "./data.js";

export const TIERS = [
  { min: 85, id: "likely_fake", label: "Likely fake" },
  { min: 65, id: "highly_suspicious", label: "Highly suspicious" },
  { min: 45, id: "suspicious", label: "Suspicious" },
  { min: 25, id: "be_careful", label: "Be careful" },
  { min: 0, id: "looks_genuine", label: "Looks genuine" },
];

const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const hasTerm = (text, term) => new RegExp(`(?<![a-z0-9])${esc(term)}(?![a-z0-9])`, "i").test(text);
const findTerms = (text, list) => list.filter((t) => hasTerm(text, t));
const inr = (n) => "₹" + Math.round(n).toLocaleString("en-IN");

function findBrand(ex) {
  const first = (ex.brand_claimed || "").toLowerCase();
  const second = (ex.product_name || "").toLowerCase();
  for (const hay of [first, second]) {
    if (!hay) continue;
    for (const b of BRANDS) if (b.aliases.some((a) => hasTerm(hay, a))) return b;
  }
  return null;
}

export function scoreListing(ex) {
  const reasons = [];
  let score = 0;
  const add = (points, type, text) => {
    reasons.push({ type, text, weight: Math.abs(points) });
    score += points;
  };

  const brand = findBrand(ex);
  const text = [ex.product_name, ex.brand_claimed, ex.description, ...(ex.suspicious_phrases || [])]
    .filter(Boolean).join(" ").toLowerCase();

  // 1. Imitation keywords
  const strong = findTerms(text, STRONG_TERMS);
  const weak = findTerms(text, WEAK_TERMS);
  if (strong.length) {
    add(Math.min(55, 45 + (strong.length - 1) * 5), "risk",
      `The listing uses imitation wording (“${strong.slice(0, 3).join("”, “")}”). Genuine sellers do not describe products this way.`);
  } else if ((ex.suspicious_phrases || []).length) {
    add(25, "risk", `The listing contains wording that hints at an imitation: “${ex.suspicious_phrases.slice(0, 2).join("”, “")}”.`);
  }
  if (weak.length && !strong.length) {
    add(8, "risk", `Vague quality claims found (“${weak.slice(0, 2).join("”, “")}”). Common on imitation listings, but also used by real sellers.`);
  }

  // 2. Price versus what a genuine item usually costs
  const price = ex.price_inr;
  let priceChecked = false;
  let refMin = null;
  let refSource = null;
  const brandFloor = brand ? (brand.floors[ex.category] ?? brand.floors.any ?? null) : null;
  const gMin = ex.typical_genuine_price_inr?.min;
  const gReliable = ex.price_estimate_confidence === "high" || ex.price_estimate_confidence === "medium";
  if (brandFloor) { refMin = brandFloor; refSource = "brand"; }
  if (gMin && gReliable && gMin > (refMin || 0)) { refMin = gMin; refSource = ex.price_estimate_confidence === "high" ? "ai_high" : "ai_medium"; }

  if (price && refMin) {
    priceChecked = true;
    const r = price / refMin;
    let pts = r < 0.1 ? 55 : r < 0.25 ? 42 : r < 0.4 ? 32 : r < 0.55 ? 22 : r < 0.7 ? 12 : r < 0.85 ? 5 : 0;
    if (refSource === "ai_medium") pts = Math.round(pts * 0.7);
    if (pts > 0) {
      const who = brand ? brand.name : (ex.brand_claimed || "this product");
      add(pts, "risk", `The price (${inr(price)}) is far below what a genuine ${who} item usually costs (about ${inr(refMin)} or more).`);
    } else {
      add(0, "ok", `The price (${inr(price)}) is in a believable range for a genuine item.`);
    }
  } else if (!price) {
    reasons.push({ type: "info", text: "No price was visible, so the price check was skipped.", weight: 0 });
  } else {
    reasons.push({ type: "info", text: "We could not find a reliable reference price for this product, so the price check was skipped.", weight: 0 });
  }

  // 3. Discount claims
  if (ex.discount_percent >= 85) add(12, "risk", `An extreme discount (${Math.round(ex.discount_percent)}% off) is a common bait on fake listings.`);
  else if (ex.discount_percent >= 70 && brand) add(8, "risk", `A ${Math.round(ex.discount_percent)}% discount on a known brand is unusual.`);

  // 4. Brand spelling / logo problems
  if (ex.brand_spelling_issue) add(40, "risk", "The brand name looks misspelled or altered, a classic trick used by imitation sellers.");

  // 5. Image and text disagree
  if (ex.image_text_mismatch) add(20, "risk", "The image does not match the product name or brand written in the listing.");

  // 6. Unrealistic claims
  if ((ex.unrealistic_claims || []).length) add(15, "risk", `Unrealistic claim: “${ex.unrealistic_claims[0]}”.`);

  // 7. Poor writing
  if (ex.text_quality_issues) add(8, "risk", "The listing text has many spelling or grammar errors, which is unusual for official brand pages.");

  // 8. Premium brand sold where brands rarely have official sellers
  const platform = (ex.platform || "").toLowerCase();
  const sellerLower = (ex.seller_name || "").toLowerCase();
  const isOfficial = !!(brand && sellerLower && (brand.aliases.some((a) => hasTerm(sellerLower, a)) || /official|authori[sz]ed|brand store/.test(sellerLower)));
  if (brand && !isOfficial && NO_OFFICIAL_PLATFORMS.some((p) => platform.includes(p))) {
    add(10, "risk", `${brand.name} products are rarely sold through ${ex.platform} by official sellers.`);
  }
  if (isOfficial) add(-15, "ok", "The seller looks like the brand’s official or authorised store.");

  // 9. Very few reviews with a near-perfect rating
  if (ex.rating >= 4.8 && ex.rating_count !== null && ex.rating_count < 10) add(5, "risk", "A near-perfect rating from very few reviews is not reliable.");

  score = Math.max(0, Math.min(100, Math.round(score)));

  // Confidence = how many checks we could actually do
  const hasName = !!ex.product_name;
  let confidence = "Low";
  if (priceChecked && hasName && ex.extraction_confidence !== "low") confidence = "High";
  else if ((priceChecked || strong.length) && hasName) confidence = "Medium";

  let tier = TIERS.find((t) => score >= t.min);
  const insufficient = !hasName && !price;
  if (insufficient) {
    tier = { id: "not_enough_info", label: "Not enough information" };
  } else if (score < 25 && !priceChecked && ex.extraction_confidence !== "high") {
    tier = { id: "cannot_verify", label: "Couldn’t verify" };
  }

  reasons.sort((a, b) => b.weight - a.weight);
  return { score, tier: { id: tier.id, label: tier.label }, confidence, reasons, referencePrice: refMin, brandMatched: brand ? brand.name : null };
}
