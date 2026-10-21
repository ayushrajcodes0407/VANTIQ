"""
VANTIQ: Multilingual Natural Language & Context Engine
Module: multilingual.py

Description:
    Provides language detection (English, Hindi Devanagari, Hinglish Roman script),
    query normalization (wake words, conversational fillers, spelling variations),
    conversational context management, and localized response formatting.
"""

import re
from typing import Dict, List, Any, Optional, Tuple

# Conversational fillers and wake words to strip for canonical intent matching
WAKE_WORDS = [
    r'\bjarvis\b', r'\bvantiq\b', r'\bassistant\b', r'\bbot\b', r'\bhey jarvis\b', r'\bhey vantiq\b'
]

CONVERSATIONAL_FILLERS = [
    r'\bbro\b', r'\bbhai\b', r'\byaar\b', r'\bplease\b', r'\bplz\b', r'\bkripya\b',
    r'\bzara\b', r'\bsun\b', r'\bsuno\b', r'\bbatao\b', r'\bbatana\b', r'\bbataiye\b',
    r'\btell me\b', r'\bcan you\b', r'\bcould you\b',
    r'\bmujhe\b', r'\bhumko\b', r'\bjust\b', r'\bactually\b'
]


# Devanagari Unicode Range: \u0900 to \u097F
DEVANAGARI_REGEX = re.compile(r'[\u0900-\u097F]')

# Common Hinglish marker words (Roman script Hindi vocabulary)
HINGLISH_MARKERS = {
    'ka', 'ki', 'ke', 'ko', 'mein', 'me', 'se', 'par', 'pe',
    'kya', 'kyu', 'kyun', 'kaun', 'kaunsa', 'kaunsi', 'kaunse',
    'kitna', 'kitni', 'kitne', 'kaisa', 'kaisi', 'kaise',
    'hai', 'hain', 'ho', 'tha', 'thi', 'the', 'hoga', 'hogi', 'honge',
    'saare', 'sare', 'sab', 'sabse', 'kuch', 'koi',
    'dikhao', 'dekhao', 'batao', 'bataye', 'bataiye', 'dekho',
    'karo', 'kariye', 'khatam', 'khatm', 'bacha', 'bache', 'bachi',
    'sasta', 'saste', 'sasti', 'mehenga', 'mehenge', 'mehangi',
    'kam', 'jyada', 'zyada', 'bhai', 'yaar', 'mujhe', 'apna', 'apne'
}


def detect_language(text: str) -> str:
    """
    Detects whether text is 'hi' (Hindi in Devanagari), 'hinglish' (Hindi in Roman script),
    or 'en' (English).
    """
    if not text:
        return 'en'

    # Check for Devanagari characters
    devanagari_chars = len(DEVANAGARI_REGEX.findall(text))
    if devanagari_chars >= 2 or (devanagari_chars > 0 and len(text.strip()) <= 10):
        return 'hi'

    # Check for Hinglish markers in Roman text
    words = re.findall(r'[a-zA-Z]+', text.lower())
    if not words:
        return 'en'

    hinglish_matches = sum(1 for w in words if w in HINGLISH_MARKERS)
    ratio = hinglish_matches / len(words)

    # If at least 2 words or >25% of words are Hinglish markers
    if hinglish_matches >= 2 or ratio >= 0.25:
        return 'hinglish'

    return 'en'


def clean_query(text: str) -> Tuple[str, str]:
    """
    Normalizes query by stripping wake words and extra filler terms.
    Returns (cleaned_query, detected_lang).
    """
    if not text:
        return "", "en"

    raw_text = text.strip()
    detected_lang = detect_language(raw_text)

    cleaned = raw_text
    # Strip wake words
    for ww in WAKE_WORDS:
        cleaned = re.sub(ww, '', cleaned, flags=re.IGNORECASE)

    # Strip conversational fillers
    for cf in CONVERSATIONAL_FILLERS:
        cleaned = re.sub(cf, '', cleaned, flags=re.IGNORECASE)

    # Clean double spaces and punctuation
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(' .,!?:;')
    return cleaned, detected_lang



class ConversationContextManager:
    """
    Stores session state for multi-turn conversational follow-ups:
    - Last listed products (for 'which one is the cheapest', 'show first one')
    - Last mentioned product (for 'what is its price', 'is it in stock')
    - Last active dataset
    - Last used language
    """
    def __init__(self):
        self.last_products: List[Dict[str, Any]] = []
        self.last_product: Optional[Dict[str, Any]] = None
        self.last_intent: Optional[str] = None
        self.last_language: str = "en"
        self.active_dataset_id: Optional[str] = None

    def update_products(self, products: List[Dict[str, Any]], language: str = "en"):
        self.last_products = products
        self.last_language = language
        if len(products) == 1:
            self.last_product = products[0]

    def update_product(self, product: Dict[str, Any], language: str = "en"):
        self.last_product = product
        self.last_language = language

    def clear(self):
        self.last_products = []
        self.last_product = None
        self.last_intent = None


# Global context instance
SESSION_CONTEXT = ConversationContextManager()


def format_multilingual_response(
    intent: str,
    lang: str,
    data: Dict[str, Any]
) -> Dict[str, str]:
    """
    Returns localized ('speak', 'display') texts based on intent and language (en, hi, hinglish).
    """
    currency = data.get("currency", "₹")

    if intent == "product_list":
        items = data.get("items", [])
        total = data.get("total", len(items))
        if total == 0:
            if lang == "hi":
                return {
                    "speak": "कैटलॉग में वर्तमान में कोई प्रोडक्ट उपलब्ध नहीं है। कैटलॉग खाली है।",
                    "display": "कैटलॉग खाली है (0 प्रोडक्ट्स)"
                }
            elif lang == "hinglish":
                return {
                    "speak": "Aapke catalogue mein abhi koi product nahi hai. Catalogue bilkul empty hai.",
                    "display": "Catalogue empty hai (0 products)"
                }
            else:
                return {
                    "speak": "There are currently no products available in the catalogue.",
                    "display": "Catalogue is empty (0 products)"
                }

        names = [p.get("name") for p in items[:5] if p.get("name")]
        sample = ", ".join(names)

        if lang == "hi":
            speak = f"आपके कैटलॉग में {total} प्रोडक्ट्स हैं, जैसे कि: {sample}।" if total > 0 else "कैटलॉग खाली है।"
            display = f"कैटलॉग: {total} प्रोडक्ट्स ({len(items)} दिखाए गए)"
        elif lang == "hinglish":
            speak = f"Aapke catalogue mein total {total} active products hain: {sample}."
            display = f"Catalogue: {total} products ({len(items)} shown)"
        else:
            speak = f"Here are the active products in your catalogue: {sample}."
            display = f"Catalogue: {total} active products ({len(items)} shown)"

        return {"speak": speak, "display": display}

    elif intent == "product_count":
        active = data.get("active", 0)
        units = data.get("units", 0.0)

        if lang == "hi":
            speak = f"कैटलॉग में कुल {active} एक्टिव प्रोडक्ट्स हैं, और कुल स्टॉक {units:,.1f} यूनिट्स है।"
            display = f"कुल प्रोडक्ट्स: {active} | कुल स्टॉक: {units:,.1f}"
        elif lang == "hinglish":
            speak = f"Catalogue mein total {active} products hain, aur sabhi milakar {units:,.1f} stock units hain."
            display = f"Total Products: {active} | Total Stock: {units:,.1f}"
        else:
            speak = f"You have {active} active products in the catalogue, with a total of {units:,.1f} stock units."
            display = f"Total Products: {active} | Stock Units: {units:,.1f}"

        return {"speak": speak, "display": display}

    elif intent == "product_stock":
        name = data.get("name", "Product")
        qty = data.get("quantity", 0.0)
        unit = data.get("unit", "units")
        reorder = data.get("reorder_level", 0.0)

        if lang == "hi":
            status_text = " (स्टॉक न्यूनतम स्तर से कम है!)" if qty <= reorder else ""
            speak = f"{name} का वर्तमान स्टॉक {qty} {unit} है{status_text}।"
            display = f"{name}: {qty} {unit} स्टॉक"
        elif lang == "hinglish":
            status_text = " (Low stock alert!)" if qty <= reorder else ""
            speak = f"{name} ka current stock {qty} {unit} hai{status_text}."
            display = f"{name}: {qty} {unit} stock"
        else:
            status_text = " (Low stock alert!)" if qty <= reorder else ""
            speak = f"The current stock for {name} is {qty} {unit}{status_text}."
            display = f"{name}: {qty} {unit} in stock"

        return {"speak": speak, "display": display}

    elif intent == "product_not_found":
        query = data.get("query", "")
        if lang == "hi":
            speak = f"माफ़ कीजिए, '{query}' नाम से कोई प्रोडक्ट कैटलॉग में नहीं मिला।"
            display = f"प्रोडक्ट नहीं मिला: '{query}'"
        elif lang == "hinglish":
            speak = f"Sorry, '{query}' naam se koi product catalogue mein nahi mila."
            display = f"Product nahi mila: '{query}'"
        else:
            speak = f"No product matching '{query}' was found in the catalogue."
            display = f"Product not found: '{query}'"

        return {"speak": speak, "display": display}

    elif intent == "inventory_summary":
        active = data.get("active", 0)
        units = data.get("units", 0.0)
        val = data.get("valuation", 0.0)
        low_count = data.get("low_count", 0)

        if lang == "hi":
            speak = f"इन्वेंटरी सारांश: कुल {active} प्रोडक्ट्स हैं, {units:,.1f} स्टॉक यूनिट्स, और कुल वैल्यू {currency}{val:,.2f} है। {low_count} प्रोडक्ट्स में स्टॉक कम है।"
            display = f"इन्वेंटरी: {active} प्रोडक्ट्स | स्टॉक: {units:,.1f} | वैल्यू: {currency}{val:,.2f}"
        elif lang == "hinglish":
            speak = f"Overall inventory status: Total {active} products hain, {units:,.1f} stock units, aur inventory valuation {currency}{val:,.2f} hai. {low_count} products low stock par hain."
            display = f"Inventory: {active} items | Stock: {units:,.1f} | Value: {currency}{val:,.2f}"
        else:
            speak = f"Overall inventory summary: {active} products, {units:,.1f} total stock units, valued at {currency}{val:,.2f}. {low_count} items are low in stock."
            display = f"Inventory: {active} items | Stock: {units:,.1f} | Valuation: {currency}{val:,.2f}"

        return {"speak": speak, "display": display}

    elif intent == "product_verify":
        issues = data.get("issues", [])
        total_checked = data.get("total_checked", 0)
        if not issues:
            if lang == "hi":
                speak = f"सत्यापन पूरा हुआ। कैटलॉग के सभी {total_checked} प्रोडक्ट्स के रिकॉर्ड वैध और सही हैं।"
                display = f"सत्यापन सफल: सभी {total_checked} प्रोडक्ट्स सही हैं"
            elif lang == "hinglish":
                speak = f"Verification complete! Catalogue ke sabhi {total_checked} products valid aur operational hain. Koi issue nahi mila."
                display = f"Verification Complete: {total_checked} products verified"
            else:
                speak = f"Verification complete. All {total_checked} catalogue products have valid prices, categories, and inventory records."
                display = f"Verification Passed: {total_checked} products verified"
        else:
            issue_summary = f"{len(issues)} issues detected"
            if lang == "hi":
                speak = f"सत्यापन में {len(issues)} प्रोडक्ट्स में समस्याएँ मिलीं (जैसे बिना कीमत या शून्य स्टॉक वाले प्रोडक्ट्स)।"
                display = f"सत्यापन चेतावनी: {len(issues)} समस्याएँ मिलीं"
            elif lang == "hinglish":
                speak = f"Verification report: {len(issues)} products mein issues mile hain (missing price ya zero stock). Details screen par hain."
                display = f"Verification Warning: {len(issues)} issues detected"
            else:
                speak = f"Product verification identified {len(issues)} items requiring attention (such as unconfigured prices or zero stock)."
                display = f"Verification Alert: {len(issues)} issues detected"

        return {"speak": speak, "display": display}

    elif intent == "lowest_stock":
        items = data.get("items", [])
        if not items:
            if lang == "hi":
                speak = "कैटलॉग में कोई एक्टिव प्रोडक्ट नहीं है।"
                display = "कोई प्रोडक्ट नहीं मिला"
            elif lang == "hinglish":
                speak = "Catalogue mein koi active product nahi hai."
                display = "Koi product nahi mila"
            else:
                speak = "No active products recorded in the catalogue."
                display = "No products found"
        else:
            names = [f"{p['name']} ({p.get('quantity_on_hand', 0)} {p.get('unit', 'units')})" for p in items[:3]]
            sample = ", ".join(names)
            if lang == "hi":
                speak = f"सबसे कम स्टॉक वाले प्रोडक्ट्स हैं: {sample}।"
                display = f"न्यूनतम स्टॉक: {sample}"
            elif lang == "hinglish":
                speak = f"Sabse kam stock wale products ye hain: {sample}."
                display = f"Lowest Stock: {sample}"
            else:
                speak = f"The products with the lowest stock quantities are: {sample}."
                display = f"Lowest Stock: {sample}"
        return {"speak": speak, "display": display}

    elif intent == "cheapest_product":
        product = data.get("product")
        if not product:
            if lang == "hi":
                speak = "कैटलॉग में कोई प्रोडक्ट नहीं मिला।"
                display = "कोई प्रोडक्ट उपलब्ध नहीं"
            elif lang == "hinglish":
                speak = "Catalogue mein koi product nahi mila."
                display = "No products available"
            else:
                speak = "No products are currently available in the catalogue."
                display = "No products available"
        else:
            name = product.get("name", "Product")
            price = product.get("selling_price", 0.0)
            if lang == "hi":
                speak = f"उपलब्ध प्रोडक्ट्स में सबसे सस्ता प्रोडक्ट {name} है, जिसका विक्रय मूल्य {currency}{price:,.2f} है।"
                display = f"सबसे सस्ता: {name} ({currency}{price:,.2f})"
            elif lang == "hinglish":
                speak = f"Inmein sabse sasta product {name} hai, jiska selling price {currency}{price:,.2f} hai."
                display = f"Cheapest: {name} ({currency}{price:,.2f})"
            else:
                speak = f"The cheapest product in the catalogue is {name}, priced at {currency}{price:,.2f}."
                display = f"Cheapest: {name} ({currency}{price:,.2f})"
        return {"speak": speak, "display": display}

    elif intent == "expensive_product":
        product = data.get("product")
        if not product:
            if lang == "hi":
                speak = "कैटलॉग में कोई प्रोडक्ट नहीं मिला।"
                display = "कोई प्रोडक्ट उपलब्ध नहीं"
            elif lang == "hinglish":
                speak = "Catalogue mein koi product nahi mila."
                display = "No products available"
            else:
                speak = "No products are currently available in the catalogue."
                display = "No products available"
        else:
            name = product.get("name", "Product")
            price = product.get("selling_price", 0.0)
            if lang == "hi":
                speak = f"उपलब्ध प्रोडक्ट्स में सबसे महँगा प्रोडक्ट {name} है, जिसका विक्रय मूल्य {currency}{price:,.2f} है।"
                display = f"सबसे महँगा: {name} ({currency}{price:,.2f})"
            elif lang == "hinglish":
                speak = f"Inmein sabse mehenga product {name} hai, jiska selling price {currency}{price:,.2f} hai."
                display = f"Most Expensive: {name} ({currency}{price:,.2f})"
            else:
                speak = f"The most expensive product in the catalogue is {name}, priced at {currency}{price:,.2f}."
                display = f"Most Expensive: {name} ({currency}{price:,.2f})"
        return {"speak": speak, "display": display}

    elif intent == "selling_price":
        product = data.get("product")
        name = product.get("name", "Product") if product else data.get("name", "Product")
        price = product.get("selling_price", 0.0) if product else data.get("price", 0.0)
        cost = product.get("purchase_price", 0.0) if product else data.get("cost", 0.0)
        if lang == "hi":
            speak = f"{name} का विक्रय मूल्य {currency}{price:,.2f} है, और लागत मूल्य {currency}{cost:,.2f} है।"
            display = f"{name}: विक्रय मूल्य = {currency}{price:,.2f} | लागत = {currency}{cost:,.2f}"
        elif lang == "hinglish":
            speak = f"{name} ka selling price {currency}{price:,.2f} hai aur purchase price {currency}{cost:,.2f} hai."
            display = f"{name}: Selling Price = {currency}{price:,.2f} | Cost = {currency}{cost:,.2f}"
        else:
            speak = f"The selling price of {name} is {currency}{price:,.2f}, with a purchase cost of {currency}{cost:,.2f}."
            display = f"{name}: Selling Price = {currency}{price:,.2f} | Cost = {currency}{cost:,.2f}"
        return {"speak": speak, "display": display}

    elif intent == "supplier_lookup":
        mode = data.get("mode", "single")
        if mode == "list":
            suppliers = data.get("suppliers", [])
            if not suppliers:
                if lang == "hi":
                    speak = "डेटाबेस में कोई पंजीकृत सप्लायर नहीं मिला।"
                    display = "कोई सप्लायर नहीं मिला"
                elif lang == "hinglish":
                    speak = "Database mein koi registered supplier nahi mila."
                    display = "No suppliers found"
                else:
                    speak = "No registered suppliers were found in the database."
                    display = "No suppliers found"
            else:
                names = [s.get("name") for s in suppliers[:4] if s.get("name")]
                sample = ", ".join(names)
                if lang == "hi":
                    speak = f"कुल {len(suppliers)} सप्लायर्स पंजीकृत हैं: {sample}।"
                    display = f"सप्लायर्स ({len(suppliers)}): {sample}"
                elif lang == "hinglish":
                    speak = f"Catalogue mein total {len(suppliers)} suppliers registered hain: {sample}."
                    display = f"Suppliers ({len(suppliers)}): {sample}"
                else:
                    speak = f"There are {len(suppliers)} registered suppliers in the database: {sample}."
                    display = f"Suppliers ({len(suppliers)}): {sample}"
        else:
            product_name = data.get("product_name", "Product")
            supplier_name = data.get("supplier_name")
            if not supplier_name:
                if lang == "hi":
                    speak = f"{product_name} कैटलॉग में है, लेकिन अभी इसके लिए कोई सप्लायर लिंक नहीं है।"
                    display = f"{product_name}: कोई सप्लायर लिंक नहीं है"
                elif lang == "hinglish":
                    speak = f"{product_name} catalogue mein registered hai, lekin abhi koi supplier linked nahi hai."
                    display = f"{product_name}: No supplier linked"
                else:
                    speak = f"Product '{product_name}' is in the catalogue, but no supplier is currently linked."
                    display = f"{product_name}: No supplier linked"
            else:
                contact = data.get("contact_name")
                extra = f" (Contact: {contact})" if contact else ""
                if lang == "hi":
                    speak = f"{product_name} के सप्लायर {supplier_name} हैं{extra}।"
                    display = f"{product_name} सप्लायर: {supplier_name}"
                elif lang == "hinglish":
                    speak = f"{product_name} ke supplier {supplier_name} hain{extra}."
                    display = f"{product_name} Supplier: {supplier_name}"
                else:
                    speak = f"The supplier for {product_name} is {supplier_name}{extra}."
                    display = f"{product_name} Supplier: {supplier_name}"
        return {"speak": speak, "display": display}

    # Default fallback
    return {
        "speak": data.get("speak", "Processed successfully."),
        "display": data.get("display", "Operation completed.")
    }


def match_multilingual_intent(query: str, lang: str = "en") -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Fast regex and phrase intent dispatcher for Hindi, Hinglish, and English queries.
    Returns (intent_name, params_dict) or None if no match.
    """
    q = query.strip()
    q_lower = q.lower()

    # Clean punctuation and wake words
    cleaned, detected_lang = clean_query(q)
    c_lower = cleaned.lower()
    active_lang = lang if lang in ("hi", "hinglish") else detected_lang

    # 1. Product Verification
    if any(phrase in c_lower for phrase in [
        'verify all the products', 'verify all products', 'verify products',
        'validate all products', 'validate products', 'check products',
        'audit all products', 'verify catalogue', 'saare products verify',
        'sare products verify', 'products verify', 'products ko verify'
    ]) or (('verify' in c_lower or 'validate' in c_lower) and ('product' in c_lower or 'catalogue' in c_lower)):
        return ("product_verify", {})

    # 2. Contextual follow-up: Cheapest / Most expensive product
    if any(phrase in c_lower for phrase in [
        'sabse sasta', 'sabse saste', 'sabse sasti', 'cheapest product',
        'which one is cheapest', 'which product is cheapest', 'cheapest one',
        'inmein sabse sasta', 'inme sabse sasta', 'sab se sasta', 'सबसे सस्ता'
    ]):
        return ("cheapest_product", {})

    if any(phrase in c_lower for phrase in [
        'sabse mehenga', 'sabse mehnge', 'sabse costly', 'most expensive',
        'highest price product', 'inmein sabse mehenga', 'सबसे महंगा', 'सबसे महँगा'
    ]):
        return ("expensive_product", {})

    # 3. Lowest stock products
    if any(phrase in c_lower for phrase in [
        'sabse kam stock', 'sab se kam stock', 'lowest stock', 'least stock',
        'sabse kam stock kin', 'sabse kam stock kiska', 'minimum stock products',
        'सबसे कम स्टॉक'
    ]):
        return ("lowest_stock_products", {})

    # 4. Out of stock products
    if any(phrase in c_lower for phrase in [
        'stock khatam', 'khatam ho gaya', 'out of stock', 'zero stock',
        'stock khatm', 'khatam products', 'स्टॉक खत्म'
    ]):
        return ("out_of_stock_products", {})

    # 5. Low stock products
    if any(phrase in c_lower for phrase in [
        'low stock wale products', 'low stock products', 'kam stock wale',
        'low stock dikhao', 'low stock items', 'कम स्टॉक'
    ]):
        return ("low_stock_products", {})

    # 6. Specific product stock query
    # E.g., "Capacitor ka stock kitna hai?", "Capacitor ka stock", "what is current stock of Capacitor"
    stock_hinglish_match = re.search(r'([a-zA-Z0-9_\-\s]+?)\s+ka\s+stock(\s+kitna\s+hai)?', c_lower)
    if stock_hinglish_match:
        cand = stock_hinglish_match.group(1).strip()
        cand = re.sub(r'^(is|iss|is product|mujhe|batao|zara)\s+', '', cand).strip()
        if cand and cand not in ('current', 'total', 'kul', 'overall', 'sab', 'saare', 'product'):
            return ("product_stock", {"product_name": cand})

    # Match "stock of <Product>" or "current stock of <Product>"
    stock_of_match = re.search(r'(?:current\s+)?stock\s+of\s+([a-zA-Z0-9_\-\s]+)', c_lower)
    if stock_of_match:
        cand = stock_of_match.group(1).strip().rstrip('?.')
        cand = re.sub(r'\b(bro|bhai|vantiq|jarvis|please)\b', '', cand).strip()
        if cand and cand not in ('product', 'catalogue', 'all', 'inventory'):
            return ("product_stock", {"product_name": cand})

    # Match Devanagari Hindi "<Product> का स्टॉक कितना है"
    hi_stock_match = re.search(r'([\u0900-\u097F\w\s]+?)\s+का\s+स्टॉक', c_lower)
    if hi_stock_match:
        cand = hi_stock_match.group(1).strip()
        if cand and cand not in ('कुल', 'सब', 'प्रोडक्ट'):
            return ("product_stock", {"product_name": cand})

    # 7. Overall / Current Stock Summary (No specific product mentioned)
    if any(phrase in c_lower for phrase in [
        'current stock', 'what is current stock', 'overall stock', 'total stock',
        'stock summary', 'inventory summary', 'kul stock', 'stock kitna hai',
        'stock status', 'current stock bro', 'current stock vantiq'
    ]):
        return ("inventory_summary", {})

    # 8. All Products / Catalogue Listing
    # E.g., "jarvis kaun kaun se products hai", "Saare products dikhao", "Sabhi products ke naam batao", "show all products"
    if any(phrase in c_lower for phrase in [
        'kaun kaun se products', 'kaun se products', 'kya kya products',
        'saare products dikhao', 'sare products dikhao', 'sab products dikhao',
        'sabhi products ke naam', 'products ke naam', 'products ki list',
        'products dikhao', 'catalogue dikhao', 'list all products',
        'show all products', 'what are all products', 'all products',
        'saare products', 'sare products', 'sab products', 'सारे प्रोडक्ट्स दिखाओ',
        'सभी प्रोडक्ट्स के नाम', 'कौन कौन से प्रोडक्ट्स', 'प्रोडक्ट्स दिखाओ'
    ]):
        return ("product_list", {})

    # 9. Total Product Count
    # E.g., "Kitne products hain?", "how many products do we have", "total products"
    if any(phrase in c_lower for phrase in [
        'kitne products', 'kitne product', 'total products count', 'how many products',
        'kul kitne product', 'kul kitne products', 'number of products', 'count products',
        'कितने प्रोडक्ट्स', 'कितने प्रोडक्ट', 'कुल कितने', 'कुल कितने प्रोडक्ट'
    ]):
        return ("product_count", {})

    # 10. Specific product selling price
    # Hinglish: "<Product> ka selling price kya hai", "<Product> ka price"
    price_hinglish_match = re.search(r'([a-zA-Z0-9_\-\s]+?)\s+ka\s+(?:selling\s+price|price|rate|bhav)(\s+kya\s+hai)?', c_lower)
    if price_hinglish_match:
        cand = price_hinglish_match.group(1).strip()
        if cand in ('is', 'iss', 'is product', 'iss product'):
            cand = "context_product"
        if cand:
            return ("product_price", {"product_name": cand})

    # English: "What is the selling price of <Product>?", "selling price of <Product>", "price of <Product>"
    price_en_match = re.search(r'(?:what\s+is\s+(?:the\s+)?)?(?:selling\s+price|sale\s+price|price|rate|cost)\s+of\s+([a-zA-Z0-9_\-\s]+)', c_lower)
    if price_en_match:
        cand = price_en_match.group(1).strip().rstrip('?.')
        cand = re.sub(r'\b(bro|bhai|vantiq|jarvis|please)\b', '', cand).strip()
        if cand and cand not in ('product', 'catalogue', 'all', 'everything'):
            return ("product_price", {"product_name": cand})

    # Hindi Devanagari: "<Product> का विक्रय मूल्य / दाम / कीमत"
    hi_price_match = re.search(r'([\u0900-\u097F\w\s]+?)\s+का\s+(?:विक्रय\s+मूल्य|मूल्य|दाम|कीमत)', c_lower)
    if hi_price_match:
        cand = hi_price_match.group(1).strip()
        if cand:
            return ("product_price", {"product_name": cand})

    # 11. Supplier Lookup
    # E.g. "Who is the supplier for Capacitor?", "supplier of Capacitor", "Capacitor ka supplier kaun hai", "list suppliers"
    if any(phrase in c_lower for phrase in ['list suppliers', 'all suppliers', 'show suppliers', 'suppliers list', 'saare suppliers', 'sabhi suppliers', 'suppliers dikhao']):
        return ("supplier_lookup", {"list_all": True})

    supp_hinglish_match = re.search(r'([a-zA-Z0-9_\-\s]+?)\s+ka\s+supplier(\s+kaun\s+hai)?', c_lower)
    if supp_hinglish_match:
        cand = supp_hinglish_match.group(1).strip()
        cand = re.sub(r'^(is|iss|is product|mujhe|batao|zara)\s+', '', cand).strip()
        if cand and cand not in ('all', 'saare', 'sab', 'product'):
            return ("supplier_lookup", {"product_name": cand})

    supp_en_match = re.search(r'(?:who\s+is\s+(?:the\s+)?)?supplier\s+(?:for|of)\s+([a-zA-Z0-9_\-\s]+)', c_lower)
    if supp_en_match:
        cand = supp_en_match.group(1).strip().rstrip('?.')
        cand = re.sub(r'\b(bro|bhai|vantiq|jarvis|please)\b', '', cand).strip()
        if cand and cand not in ('product', 'catalogue', 'all'):
            return ("supplier_lookup", {"product_name": cand})

    # 12. Conceptual / Business Difference Explanations
    # E.g. "Purchase price aur selling price mein kya difference hai?"
    # "Gross margin aur markup mein kya difference hai?"
    if any(term in c_lower for term in ['difference', 'antar', 'farq']) or 'kya difference' in c_lower:
        if ('purchase price' in c_lower and 'selling price' in c_lower) or ('cost price' in c_lower and 'selling price' in c_lower):
            return ("explanation", {"concept": "purchase price and selling price difference", "language": active_lang})
        if ('gross margin' in c_lower and 'markup' in c_lower) or ('margin' in c_lower and 'markup' in c_lower):
            return ("explanation", {"concept": "gross margin and markup difference", "language": active_lang})

    return None

