// ============================================================
//  SafeShop AI v2 – knowledge lists you can edit
//  Edit this file on GitHub (pencil icon) and commit: the site
//  redeploys itself in about a minute.
// ============================================================

// Phrases that sellers use for imitation products.
// Matching is whole-word and case-insensitive.
export const STRONG_TERMS = [
  "first copy", "1st copy", "master copy", "master piece", "mirror copy", "a1 copy", "ab copy",
  "super copy", "hi copy", "high copy", "copy product", "7a", "7a quality",
  "7a grade", "aaa quality", "aaa grade", "replica", "clone", "dupe",
  "not original", "non original", "same as original", "100% copy", "duplicate product",
];

// Weaker hints. Real products sometimes use these too, so they add little.
export const WEAK_TERMS = [
  "premium quality", "imported quality", "export quality", "branded quality",
  "inspired by", "look alike", "lookalike", "original look", "factory outlet",
  "surplus", "oem quality", "branded look",
];

// Platforms/channels where brands rarely have an official seller account.
export const NO_OFFICIAL_PLATFORMS = ["meesho", "shopsy", "indiamart", "instagram", "whatsapp", "facebook", "telegram", "olx"];

// Brand list. "floors" = the LOWEST price (in rupees) at which a genuine item of
// that category is realistically sold. They are deliberately conservative
// (low) so that real sale prices are not flagged. Check each brand's official
// website and adjust. "any" applies to every category.
export const BRANDS = [
  { name: "Nike", aliases: ["nike"], tier: "premium", floors: { footwear: 1000, clothing: 700, bags: 900 } },
  { name: "Adidas", aliases: ["adidas"], tier: "premium", floors: { footwear: 1000, clothing: 600, bags: 800 } },
  { name: "Puma", aliases: ["puma"], tier: "premium", floors: { footwear: 900, clothing: 500, bags: 700 } },
  { name: "Reebok", aliases: ["reebok"], tier: "premium", floors: { footwear: 800, clothing: 500 } },
  { name: "Skechers", aliases: ["skechers"], tier: "premium", floors: { footwear: 1500 } },
  { name: "New Balance", aliases: ["new balance"], tier: "premium", floors: { footwear: 2500, clothing: 1200 } },
  { name: "Converse", aliases: ["converse"], tier: "premium", floors: { footwear: 1800 } },
  { name: "Vans", aliases: ["vans"], tier: "premium", floors: { footwear: 2000 } },
  { name: "Crocs", aliases: ["crocs"], tier: "premium", floors: { footwear: 1300 } },
  { name: "Under Armour", aliases: ["under armour", "under armor"], tier: "premium", floors: { clothing: 800, footwear: 2000 } },
  { name: "ASICS", aliases: ["asics"], tier: "premium", floors: { footwear: 2500 } },
  { name: "Levi's", aliases: ["levi's", "levis", "levi’s"], tier: "premium", floors: { clothing: 1000 } },
  { name: "The North Face", aliases: ["the north face", "north face"], tier: "premium", floors: { clothing: 2000, bags: 2500 } },
  { name: "Tommy Hilfiger", aliases: ["tommy hilfiger"], tier: "premium", floors: { clothing: 1200, watch: 5000, footwear: 2000, bags: 2500 } },
  { name: "Calvin Klein", aliases: ["calvin klein"], tier: "premium", floors: { clothing: 800, watch: 5000 } },
  { name: "U.S. Polo Assn.", aliases: ["us polo", "u.s. polo"], tier: "premium", floors: { clothing: 600, footwear: 1000 } },
  { name: "Lacoste", aliases: ["lacoste"], tier: "premium", floors: { clothing: 2500, footwear: 4000 } },
  { name: "Ray-Ban", aliases: ["ray-ban", "rayban", "ray ban"], tier: "premium", floors: { eyewear: 3500 } },
  { name: "Oakley", aliases: ["oakley"], tier: "premium", floors: { eyewear: 4000 } },
  { name: "Apple", aliases: ["apple", "iphone", "airpods", "macbook", "ipad"], tier: "premium", floors: { electronics: 1500, mobile_accessory: 1500, watch: 20000 } },
  { name: "Samsung", aliases: ["samsung"], tier: "premium", floors: { electronics: 500, mobile_accessory: 500 } },
  { name: "Sony", aliases: ["sony"], tier: "premium", floors: { electronics: 1500 } },
  { name: "JBL", aliases: ["jbl"], tier: "premium", floors: { electronics: 1000 } },
  { name: "Bose", aliases: ["bose"], tier: "premium", floors: { electronics: 8000 } },
  { name: "Beats", aliases: ["beats by dre", "beats"], tier: "premium", floors: { electronics: 4000 } },
  { name: "Marshall", aliases: ["marshall"], tier: "premium", floors: { electronics: 8000 } },
  { name: "Casio", aliases: ["casio"], tier: "mid", floors: { watch: 1000 } },
  { name: "G-Shock", aliases: ["g-shock", "g shock", "gshock"], tier: "premium", floors: { watch: 4500 } },
  { name: "Fossil", aliases: ["fossil"], tier: "premium", floors: { watch: 5000 } },
  { name: "Daniel Wellington", aliases: ["daniel wellington"], tier: "premium", floors: { watch: 8000 } },
  { name: "Huda Beauty", aliases: ["huda beauty"], tier: "premium", floors: { beauty: 1500 } },
  { name: "Fenty Beauty", aliases: ["fenty"], tier: "premium", floors: { beauty: 1500 } },
  { name: "Dyson", aliases: ["dyson"], tier: "premium", floors: { any: 15000 } },
  { name: "LEGO", aliases: ["lego"], tier: "premium", floors: { toys: 400 } },
  { name: "Michael Kors", aliases: ["michael kors"], tier: "premium", floors: { bags: 6000, watch: 8000 } },
  { name: "Coach", aliases: ["coach"], tier: "premium", floors: { bags: 8000 } },
  { name: "Guess", aliases: ["guess"], tier: "premium", floors: { bags: 3000, watch: 4000 } },
  { name: "Swarovski", aliases: ["swarovski"], tier: "premium", floors: { jewellery: 3000 } },
  { name: "Pandora", aliases: ["pandora"], tier: "premium", floors: { jewellery: 3000 } },
  // Luxury: nothing genuine is sold below about ₹15,000
  ...["Gucci", "Louis Vuitton", "Prada", "Chanel", "Dior", "Balenciaga", "Versace", "Burberry", "Hermès", "Rolex", "Omega", "Tag Heuer", "Cartier"]
    .map((n) => ({ name: n, aliases: [n.toLowerCase().replace("è", "e"), n.toLowerCase()], tier: "luxury", floors: { any: 15000 } })),
];
