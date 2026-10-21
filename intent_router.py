"""
J.A.R.V.I.S. Central Intent Router & Intelligence Dispatcher
Module: intent_router.py
Author: Antigravity AI Engineering
Description:
    Provides unified, deterministic intent classification and data source resolution
    for both voice and typed console orders in J.A.R.V.I.S.:
    1. Product Catalogue Queries
    2. Inventory & Stock Audits
    3. Dataset Summaries & Dimensions
    4. Column-level Profiling, Statistics, Filtering, and Grouping
    5. Data Quality and Missing Values
    6. Commercial Business Intelligence & Report Synthesis
    7. Assistant Protocols (Diagnostics, Jokes, Media, Wikipedia)
"""

import re
import datetime
import logging
from typing import Dict, List, Any, Optional, Tuple

import requests
import pyjokes
import psutil
import wikipedia
import platform

import database
import dataset_intelligence
import local_llm

logger = logging.getLogger("JARVIS-IntentRouter")


def resolve_dataset_from_query(query: str, db_path: Optional[str] = None) -> Tuple[Optional[str], Optional[str], Optional[List[Dict[str, Any]]]]:
    """
    Attempts to identify an explicitly mentioned dataset by filename, dataset ID, or source name.
    Returns: (matched_dataset_id, status, candidate_datasets)
    status can be: 'single_match', 'multiple_matches', 'no_match'
    """
    q_lower = query.lower()

    # Look for dataset ID pattern (e.g. ds_1234567890ab)
    id_match = re.search(r'\b(ds_[0-9a-f]{8,16})\b', q_lower)
    if id_match:
        ds_id = id_match.group(1)
        ds = database.get_dataset_by_id(ds_id, db_path=db_path)
        if ds:
            return ds["id"], "single_match", None

    # Look for explicit file mentions with extensions (.xlsx, .xls, .pdf, .csv)
    file_match = re.search(r'\b([a-zA-Z0-9_\-\.\ ]+\.(xlsx|xls|pdf|csv))\b', query, re.IGNORECASE)
    if file_match:
        fn = file_match.group(1).strip()
        ds_res = database.list_datasets(search=fn, db_path=db_path)
        matches = ds_res.get("datasets") or ds_res.get("items") or []
        if len(matches) == 1:
            return matches[0]["id"], "single_match", None
        elif len(matches) > 1:
            return None, "multiple_matches", matches

    # Check for "in <dataset>", "for <dataset>", "from <dataset>", "dataset <name>"
    triggers = [r'\bin dataset ([a-zA-Z0-9_\-]+)\b', r'\bfrom dataset ([a-zA-Z0-9_\-]+)\b', r'\bfor dataset ([a-zA-Z0-9_\-]+)\b', r'\bdataset ([a-zA-Z0-9_\-]+)\b']
    for pattern in triggers:
        m = re.search(pattern, q_lower)
        if m:
            target_name = m.group(1).strip()
            ds_res = database.list_datasets(search=target_name, db_path=db_path)
            matches = ds_res.get("datasets") or ds_res.get("items") or []
            if len(matches) == 1:
                return matches[0]["id"], "single_match", None
            elif len(matches) > 1:
                return None, "multiple_matches", matches

    return None, "no_match", None


def get_effective_dataset_id(query: str, context: Optional[Dict[str, Any]] = None, db_path: Optional[str] = None) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Resolves the target dataset ID using query mentions, active context, or most recent saved dataset.
    Returns: (dataset_id, disambiguation_response_or_none)
    """
    context = context or {}

    # 1. Check if user explicitly mentioned a dataset
    ds_id, status, candidates = resolve_dataset_from_query(query, db_path=db_path)
    if status == "multiple_matches" and candidates:
        names = ", ".join([f"'{c['original_filename']}' (ID: {c['id']})" for c in candidates[:3]])
        speak_text = f"Boss, I found multiple datasets matching your request: {names}. Please specify which dataset or ID you would like me to analyze."
        disambiguation = {
            "speak": speak_text,
            "display": f"Multiple datasets matched: {len(candidates)} found",
            "action": "dataset_clarify",
            "source": "Saved Dataset Library",
            "source_type": "dataset",
            "candidates": candidates[:5],
            "follow_ups": [f"Summarise dataset {c['id']}" for c in candidates[:3]]
        }
        return None, disambiguation

    if ds_id:
        return ds_id, None

    # 2. Check active context (CURRENT_FILE_INFO or active_dataset_id)
    if context.get("active_dataset_id"):
        return context["active_dataset_id"], None
    if context.get("current_file_info", {}).get("dataset_id"):
        return context["current_file_info"]["dataset_id"], None

    # 3. Fallback to latest active dataset in SQLite
    ds_list_res = database.list_datasets(page=1, page_size=1, db_path=db_path)
    latest = ds_list_res.get("datasets") or ds_list_res.get("items") or []
    if latest:
        return latest[0]["id"], None

    return None, None


def route_intent(raw_command: str, context: Optional[Dict[str, Any]] = None, db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Central intent routing and execution engine for J.A.R.V.I.S.
    Guarantees deterministic execution across product catalogue, inventory,
    tabular dataset queries, business intelligence, and assistant commands.
    """
    cmd = (raw_command or "").strip()
    c_lower = cmd.lower()
    context = context or {}

    if not cmd:
        return {
            "speak": "I am standing by, boss. Please give an order.",
            "display": "Awaiting tactical order...",
            "action": "none",
            "source": "J.A.R.V.I.S. Core",
            "source_type": "system"
        }

    cat_conn = database.get_connection(db_path) if db_path else None
    try:
        return _route_intent_internal(cmd, c_lower, context, db_path, cat_conn)
    finally:
        if cat_conn:
            try:
                cat_conn.close()
            except Exception:
                pass


# =========================================================================
# DETERMINISTIC RESPONSE BUILDERS (Executed by both LLM & Regex Matchers)
# =========================================================================

def _build_product_list_response(cat_conn: Any, source_label: str = "Product Catalogue") -> Dict[str, Any]:
    prods = database.list_products(is_active=True, page_size=20, conn=cat_conn)
    total = prods["total_count"]
    items = prods["items"]

    if total == 0:
        speak_text = "Boss, the product catalogue is currently empty. There are zero products recorded. You can add products manually via the Catalogue modal or map an imported spreadsheet."
        return {
            "speak": speak_text,
            "display": "Catalogue: 0 active products (Empty)",
            "action": "catalogue_list",
            "source": source_label,
            "source_type": "catalogue",
            "total_count": 0,
            "match_count": 0,
            "table": {"columns": ["SKU", "NAME", "CATEGORY", "STOCK", "SELLING PRICE", "STATUS"], "rows": []},
            "follow_ups": ["Open Catalogue Modal", "Map spreadsheet to catalogue"]
        }

    sample_names = ", ".join([p["name"] for p in items[:3]])
    more_str = f" and {total - 3} more" if total > 3 else ""
    speak_text = f"Boss, there are {total} active products in the catalogue, including {sample_names}{more_str}."

    table_rows = []
    for p in items:
        status_str = "OUT OF STOCK" if p.get("is_out_of_stock") else ("LOW STOCK" if p.get("is_low_stock") else "IN STOCK")
        table_rows.append({
            "id": p.get("id"),
            "sku": p.get("sku") or "--",
            "name": p.get("name"),
            "category": p.get("category") or "General",
            "stock": f"{p.get('quantity_on_hand', 0)} {p.get('unit', 'piece')}",
            "selling_price": f"₹{p.get('selling_price', 0):,.2f}",
            "status": status_str
        })

    return {
        "speak": speak_text,
        "display": f"Catalogue: {total} active products ({len(items)} shown)",
        "action": "catalogue_list",
        "source": source_label,
        "source_type": "catalogue",
        "total_count": total,
        "match_count": len(items),
        "table": {
            "columns": ["SKU", "NAME", "CATEGORY", "STOCK", "SELLING PRICE", "STATUS"],
            "rows": table_rows
        },
        "products": items,
        "follow_ups": ["Which products are low in stock?", "Which products are out of stock?", "Check inventory summary"]
    }


def _build_product_count_response(cat_conn: Any, source_label: str = "Product Catalogue") -> Dict[str, Any]:
    summary = database.get_inventory_summary(conn=cat_conn)
    active = summary["active_products"]
    units = summary["total_stock_units"]
    speak_text = f"Boss, we have {active} active products in the catalogue, totaling {units:,.1f} stock units across all inventory lines."
    return {
        "speak": speak_text,
        "display": f"Total Products: {active} | Stock Units: {units:,.1f}",
        "action": "catalogue_count",
        "source": source_label,
        "source_type": "catalogue",
        "total_count": active,
        "summary": summary,
        "follow_ups": ["What are all products?", "Which products are low in stock?"]
    }


def _build_low_stock_response(cat_conn: Any, source_label: str = "Inventory Ledger") -> Dict[str, Any]:
    res = database.list_products(low_stock=True, is_active=True, conn=cat_conn)
    items = res["items"]
    if not items:
        speak_text = "Boss, all active catalogue products have sufficient stock levels above their reorder thresholds."
        rows = []
    else:
        names = [f"{p['name']} ({p['quantity_on_hand']}/{p['reorder_level']} {p['unit']})" for p in items[:3]]
        speak_text = f"Boss, there are {len(items)} products below reorder thresholds: " + ", ".join(names) + "."
        rows = [{
            "sku": p.get("sku") or "--",
            "name": p.get("name"),
            "stock": f"{p.get('quantity_on_hand')} {p.get('unit')}",
            "reorder_level": f"{p.get('reorder_level')} {p.get('unit')}"
        } for p in items]

    return {
        "speak": speak_text,
        "display": f"Low Stock: {len(items)} items below reorder",
        "action": "catalogue_low_stock",
        "source": source_label,
        "source_type": "catalogue",
        "match_count": len(items),
        "table": {"columns": ["SKU", "NAME", "STOCK", "REORDER LEVEL"], "rows": rows},
        "items": items,
        "follow_ups": ["Which products are out of stock?", "Show all products"]
    }


def _build_out_of_stock_response(cat_conn: Any, source_label: str = "Inventory Ledger") -> Dict[str, Any]:
    res = database.list_products(out_of_stock=True, is_active=True, conn=cat_conn)
    items = res["items"]
    if not items:
        speak_text = "Boss, excellent news: there are currently zero products out of stock in the catalogue."
        rows = []
    else:
        names = [f"{p['name']} (SKU: {p['sku'] or 'N/A'})" for p in items[:3]]
        speak_text = f"Boss, there are {len(items)} products currently out of stock: " + ", ".join(names) + "."
        rows = [{
            "sku": p.get("sku") or "--",
            "name": p.get("name"),
            "category": p.get("category") or "General",
            "selling_price": f"₹{p.get('selling_price', 0):,.2f}"
        } for p in items]

    return {
        "speak": speak_text,
        "display": f"Out of Stock: {len(items)} items",
        "action": "catalogue_out_of_stock",
        "source": source_label,
        "source_type": "catalogue",
        "match_count": len(items),
        "table": {"columns": ["SKU", "NAME", "CATEGORY", "SELLING PRICE"], "rows": rows},
        "items": items,
        "follow_ups": ["Which products are low in stock?", "Show all products"]
    }


def _build_selling_price_response(target: str, cat_conn: Any, source_label: str = "Product Catalogue") -> Dict[str, Any]:
    target = target.rstrip('?.')
    res = database.list_products(search=target, is_active=True, conn=cat_conn)
    items = res["items"]

    if not items:
        speak_text = f"Boss, no product matching '{target}' was found in the catalogue."
        return {
            "speak": speak_text,
            "display": f"Price: No match for '{target}'",
            "action": "catalogue_selling_price",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": 0
        }
    elif len(items) > 1:
        candidates = ", ".join([f"{p['name']} (SKU: {p['sku'] or 'N/A'})" for p in items[:3]])
        speak_text = f"Boss, multiple products match '{target}': {candidates}. Please clarify the exact SKU or name."
        return {
            "speak": speak_text,
            "display": f"Multiple matches for '{target}'",
            "action": "catalogue_selling_price",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": len(items),
            "candidates": items[:5]
        }
    else:
        p = items[0]
        speak_text = f"Boss, the selling price of {p['name']} is {p['selling_price']} {p['currency']}. Purchase cost is {p['purchase_price']} {p['currency']}."
        return {
            "speak": speak_text,
            "display": f"{p['name']}: Selling Price = ₹{p['selling_price']:,.2f} | Cost = ₹{p['purchase_price']:,.2f}",
            "action": "catalogue_selling_price",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": 1,
            "product": p,
            "follow_ups": [f"What is the stock of {p['name']}?"]
        }


def _build_stock_response(target: str, cat_conn: Any, source_label: str = "Inventory Balance") -> Dict[str, Any]:
    target = target.rstrip('?.')
    res = database.list_products(search=target, is_active=True, conn=cat_conn)
    items = res["items"]

    if not items:
        speak_text = f"Boss, no product matching '{target}' was found in the catalogue."
        return {
            "speak": speak_text,
            "display": f"Stock: No match for '{target}'",
            "action": "catalogue_stock",
            "source": "Product Catalogue",
            "source_type": "catalogue",
            "match_count": 0,
            "follow_ups": ["What are all products?"]
        }
    elif len(items) > 1:
        candidates = ", ".join([f"{p['name']} (SKU: {p['sku'] or 'N/A'})" for p in items[:3]])
        speak_text = f"Boss, multiple products match '{target}': {candidates}. Please clarify the exact SKU or name."
        return {
            "speak": speak_text,
            "display": f"Multiple Matches ({len(items)}): {candidates}",
            "action": "catalogue_stock",
            "source": "Product Catalogue",
            "source_type": "catalogue",
            "match_count": len(items),
            "candidates": items[:5],
            "follow_ups": [f"What is the stock of {p['name']}?" for p in items[:3]]
        }
    else:
        p = items[0]
        speak_text = f"Boss, current stock of {p['name']} is {p['quantity_on_hand']} {p['unit']}. Reorder threshold is {p['reorder_level']} {p['unit']}."
        return {
            "speak": speak_text,
            "display": f"{p['name']}: {p['quantity_on_hand']} {p['unit']} in stock (Reorder: {p['reorder_level']})",
            "action": "catalogue_stock",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": 1,
            "product": p,
            "follow_ups": [f"What is the selling price of {p['name']}?", "Show all products"]
        }


def _build_no_price_response(cat_conn: Any, source_label: str = "Product Catalogue") -> Dict[str, Any]:
    all_prods = database.list_products(is_active=True, page_size=100, conn=cat_conn)["items"]
    missing_price = [p for p in all_prods if (p.get("selling_price") is None or p.get("selling_price") <= 0)]
    if not missing_price:
        speak_text = "Boss, all active products in the catalogue have valid selling prices configured."
        rows = []
    else:
        names = ", ".join([p["name"] for p in missing_price[:3]])
        speak_text = f"Boss, there are {len(missing_price)} product(s) without a selling price, including {names}."
        rows = [{"sku": p.get("sku") or "--", "name": p.get("name"), "cost": p.get("purchase_price", 0)} for p in missing_price]

    return {
        "speak": speak_text,
        "display": f"Unpriced Products: {len(missing_price)} items",
        "action": "catalogue_no_price",
        "source": source_label,
        "source_type": "catalogue",
        "total_count": len(missing_price),
        "table": {"columns": ["SKU", "NAME", "PURCHASE COST"], "rows": rows},
        "follow_ups": ["What are all products?", "Show products below reorder level"]
    }


def _build_find_product_response(target: str, cat_conn: Any, source_label: str = "Product Catalogue") -> Dict[str, Any]:
    target = target.rstrip('?.')
    res = database.list_products(search=target, is_active=True, conn=cat_conn)
    items = res["items"]

    if not items:
        speak_text = f"Boss, no product matching '{target}' was found in the saved catalogue."
        return {
            "speak": speak_text,
            "display": f"No product found for query: '{target}'",
            "action": "catalogue_find",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": 0
        }
    elif len(items) > 1:
        candidates = ", ".join([f"{p['name']} (SKU: {p['sku'] or 'N/A'})" for p in items[:3]])
        speak_text = f"Boss, I found {len(items)} matching products: {candidates}. Please clarify which product you require."
        return {
            "speak": speak_text,
            "display": f"Multiple matches for '{target}': {len(items)} products",
            "action": "catalogue_find",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": len(items),
            "candidates": items[:5]
        }
    else:
        p = items[0]
        speak_text = f"Boss, product {p['name']} (SKU: {p['sku'] or 'N/A'}) has {p['quantity_on_hand']} {p['unit']} in stock, priced at {p['selling_price']} {p['currency']}."
        return {
            "speak": speak_text,
            "display": f"Found: {p['name']} | Stock: {p['quantity_on_hand']} {p['unit']} | Price: ₹{p['selling_price']:,.2f}",
            "action": "catalogue_find",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": 1,
            "product": p,
            "follow_ups": [f"What is the selling price of {p['name']}?", "Show all products"]
        }


def _build_purchase_cost_response(target: str, cat_conn: Any, source_label: str = "Product Catalogue") -> Dict[str, Any]:
    target = target.rstrip('?.')
    res = database.list_products(search=target, is_active=True, conn=cat_conn)
    items = res["items"]

    if not items:
        speak_text = f"Boss, no product matching '{target}' was found in the catalogue."
        return {
            "speak": speak_text,
            "display": f"Cost: No match for '{target}'",
            "action": "catalogue_price",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": 0
        }
    elif len(items) > 1:
        candidates = ", ".join([f"{p['name']} (SKU: {p['sku'] or 'N/A'})" for p in items[:3]])
        speak_text = f"Boss, multiple products match '{target}': {candidates}. Please clarify the exact SKU or name."
        return {
            "speak": speak_text,
            "display": f"Multiple matches for '{target}'",
            "action": "catalogue_price",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": len(items),
            "candidates": items[:5]
        }
    else:
        p = items[0]
        speak_text = f"Boss, the purchase price of {p['name']} is {p['purchase_price']} {p['currency']}. Current selling price is {p['selling_price']} {p['currency']}."
        return {
            "speak": speak_text,
            "display": f"{p['name']}: Cost = ₹{p['purchase_price']:,.2f} | Selling = ₹{p['selling_price']:,.2f}",
            "action": "catalogue_price",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": 1,
            "product": p
        }


def _handle_bi_inventory(context: Dict[str, Any], db_path: Optional[str]) -> Dict[str, Any]:
    bi_rep = context.get("current_bi_report")
    if not bi_rep:
        ds_res = database.list_datasets(page=1, page_size=1, db_path=db_path)
        latest_ds = ds_res.get("datasets") or ds_res.get("items") or []
        if latest_ds:
            rep_record = database.get_latest_report_for_dataset(latest_ds[0]["id"], db_path=db_path)
            if rep_record:
                bi_rep = rep_record.get("report_content")

    if not bi_rep:
        msg = "No dataset loaded, Boss. Please upload product inventory data first."
        return {"speak": msg, "display": msg, "action": "bi_no_data", "source": "BI Engine", "source_type": "report"}

    inv = bi_rep.get("inventory", {})
    if not inv.get("computed"):
        missing = ", ".join(inv.get("missing_fields", ["Quantity / Stock"]))
        speak_text = f"Inventory metrics cannot be computed, Boss. The required fields ({missing}) are missing from this dataset."
        return {"speak": speak_text, "display": speak_text, "action": "bi_inventory_unavailable", "source": "BI Inventory", "source_type": "report"}

    low_items = inv.get("low_stock_items", [])
    total_units = inv.get("total_units", 0)
    speak_text = f"Boss, recorded inventory total is {total_units} units. {len(low_items)} items are flagged for low stock or reorder."
    return {
        "speak": speak_text,
        "display": f"Inventory: {total_units} units | {len(low_items)} low-stock alerts",
        "action": "bi_inventory",
        "source": "Inventory Analytics",
        "source_type": "report",
        "inventory": inv,
        "low_stock_items": low_items,
        "follow_ups": ["Show all products", "Which products are low in stock?"]
    }


def _route_intent_internal(cmd: str, c_lower: str, context: Dict[str, Any], db_path: Optional[str], cat_conn: Any) -> Dict[str, Any]:
    # =========================================================================
    # 0A. DIRECT CONCEPTUAL / MULTILINGUAL EXPLANATION (OLLAMA LOCAL LLM)
    # =========================================================================
    is_explanation_cmd = (
        ('in hindi' in c_lower) or
        ('in french' in c_lower) or
        ('in spanish' in c_lower) or
        ('explain gross margin' in c_lower) or
        (c_lower.startswith('explain ') and not c_lower.startswith(('explain the findings', 'explain findings')) and any(w in c_lower for w in [
            'gross margin', 'margin', 'reorder level', 'profit', 'markup', 'cash flow',
            'inventory turnover', 'ebitda', 'cogs'
        ])) or
        (c_lower.startswith('define ') and any(w in c_lower for w in [
            'gross margin', 'margin', 'reorder level', 'profit', 'markup'
        ]))
    )
    if is_explanation_cmd:
        lang = "Hindi" if "hindi" in c_lower else ("French" if "french" in c_lower else ("Spanish" if "spanish" in c_lower else "English"))
        concept = cmd
        for pfx in ['explain', 'what is', 'define']:
            if c_lower.startswith(pfx):
                concept = cmd[len(pfx):].strip()
                break
        concept = re.sub(r'\bin (hindi|english|french|spanish|german)\b', '', concept, flags=re.IGNORECASE).strip('?. ')
        expl = local_llm.generate_explanation(concept or cmd, language=lang)
        return {
            "speak": expl.get("content", f"Boss, here is the explanation for {concept or cmd}."),
            "display": expl.get("content", ""),
            "action": "llm_explanation",
            "source": f"Local AI ({expl.get('model', 'offline')})",
            "source_type": "llm",
            "explanation": expl.get("content", ""),
            "concept": concept or cmd,
            "language": lang,
            "inference_time_seconds": expl.get("inference_time_seconds"),
            "follow_ups": ["Show all products", "How many products do we have?"]
        }

    # High-precision legacy BI telemetry check
    if any(k in c_lower for k in ['low stock status', 'inventory status', 'bi inventory', 'stock status']):
        return _handle_bi_inventory(context, db_path)

    if any(k in c_lower for k in ['explain the findings', 'top findings', 'key findings', 'explain findings']):
        # Delegate directly to Section 3D (Key Findings)
        pass
    else:
        # =========================================================================
        # 0B. LOCAL LLM INTENT INTERPRETATION & DISPATCH
        # =========================================================================
        # Translates natural language into validated canonical intent.
        # Executes deterministic calculations & database queries. Zero hallucination.
        llm_intent_data = local_llm.interpret_natural_language(cmd, context=context)
        if llm_intent_data and llm_intent_data.get("intent") in local_llm.CANONICAL_INTENTS:
            intent = llm_intent_data["intent"]
            params = llm_intent_data.get("parameters", {})
            entity = llm_intent_data.get("entity", "")
            model_name = llm_intent_data.get("model", "qwen3:4b-instruct")

            if intent == "product_list":
                return _build_product_list_response(cat_conn, source_label="Product Catalogue")

            elif intent == "product_count":
                return _build_product_count_response(cat_conn, source_label="Product Catalogue")

            elif intent == "low_stock_products":
                return _build_low_stock_response(cat_conn, source_label="Inventory Ledger")

            elif intent == "out_of_stock_products":
                return _build_out_of_stock_response(cat_conn, source_label="Inventory Ledger")

            elif intent == "inventory_summary":
                return _build_product_count_response(cat_conn, source_label="Product Catalogue")

            elif intent == "product_stock":
                target = params.get("target_name") or params.get("product_name") or params.get("name") or params.get("sku") or entity
                if target and target.lower() not in ("product", "general", "none"):
                    return _build_stock_response(target, cat_conn, source_label="Inventory Balance")

            elif intent == "products_without_price":
                return _build_no_price_response(cat_conn, source_label="Product Catalogue")

            elif intent in ("product_price", "product_cost"):
                target = params.get("target_name") or params.get("product_name") or params.get("name") or params.get("sku") or entity
                if target and target.lower() not in ("product", "general", "none"):
                    op = str(params.get("operation") or llm_intent_data.get("operation") or "").lower()
                    if any(w in c_lower for w in ['purchase', 'cost', 'buy']) or 'purchase' in op or 'cost' in op:
                        return _build_purchase_cost_response(target, cat_conn, source_label="Product Catalogue")
                    return _build_selling_price_response(target, cat_conn, source_label="Product Catalogue")

            elif intent == "product_search":
                target = params.get("target_name") or params.get("product_name") or params.get("name") or params.get("sku") or entity
                if target and target.lower() not in ("product", "general", "none"):
                    return _build_find_product_response(target, cat_conn, source_label="Product Catalogue")

            elif intent == "bi_inventory":
                return _handle_bi_inventory(context, db_path)

            elif intent == "explanation":
                lang = params.get("language") or ("Hindi" if "hindi" in c_lower else "English")
                concept = params.get("concept") or entity or cmd
                expl = local_llm.generate_explanation(concept, language=lang)
                if expl.get("success"):
                    return {
                        "speak": expl["content"],
                        "display": expl["content"],
                        "action": "llm_explanation",
                        "source": f"Local AI ({model_name})",
                        "source_type": "llm",
                        "explanation": expl["content"],
                        "concept": concept,
                        "language": lang,
                        "inference_time_seconds": expl.get("inference_time_seconds"),
                        "follow_ups": ["Show all products", "How many products do we have?"]
                    }

    # =========================================================================
    # 1. PRODUCT CATALOGUE & INVENTORY INTENTS (Deterministic Fallback)
    # =========================================================================

    # 1A. All Products / Catalogue Listing
    is_catalogue_list = any(k in c_lower for k in [
        'what are all products', 'what are the products', 'all products', 'list all products',
        'show all products', 'show products', 'list products', 'catalogue products',
        'what products do we have', 'get products', 'catalogue list', 'view products'
    ])
    if is_catalogue_list:
        return _build_product_list_response(cat_conn, source_label="Product Catalogue")

    # 1B. Total Product Count
    if any(k in c_lower for k in ['how many products do we have', 'how many products', 'total products count', 'product count', 'number of products']):
        return _build_product_count_response(cat_conn, source_label="Product Catalogue")

    # 1C. Products Without Selling Price
    if any(k in c_lower for k in ['no selling price', 'missing selling price', 'products without selling price', 'which products have no price']):
        all_prods = database.list_products(is_active=True, page_size=100, conn=cat_conn)["items"]
        missing_price = [p for p in all_prods if (p.get("selling_price") is None or p.get("selling_price") <= 0)]
        if not missing_price:
            speak_text = "Boss, all active products in the catalogue have valid selling prices configured."
            rows = []
        else:
            names = ", ".join([p["name"] for p in missing_price[:3]])
            speak_text = f"Boss, there are {len(missing_price)} product(s) without a selling price, including {names}."
            rows = [{"sku": p.get("sku") or "--", "name": p.get("name"), "cost": p.get("purchase_price", 0)} for p in missing_price]

        return {
            "speak": speak_text,
            "display": f"Unpriced Products: {len(missing_price)} items",
            "action": "catalogue_no_price",
            "source": "Product Catalogue",
            "source_type": "catalogue",
            "total_count": len(missing_price),
            "table": {"columns": ["SKU", "NAME", "PURCHASE COST"], "rows": rows},
            "follow_ups": ["What are all products?", "Show products below reorder level"]
        }

    # 1D. Low Stock & Reorder Checks
    if any(k in c_lower for k in ['which products are low in stock', 'products low in stock', 'low stock products', 'what products are low in stock', 'show products below reorder level', 'products below reorder level', 'below reorder level']):
        return _build_low_stock_response(cat_conn, source_label="Inventory Ledger")

    # 1E. Out of Stock
    if any(k in c_lower for k in ['which products are out of stock', 'products out of stock', 'out of stock products', 'what is out of stock']):
        return _build_out_of_stock_response(cat_conn, source_label="Inventory Ledger")

    # 1F. Specific Product Stock Check
    if any(k in c_lower for k in ['current stock of', 'stock of product', 'what is the stock of', 'how much stock do we have for', 'how much stock for', 'stock of']):
        target = c_lower
        for pfx in ['how much stock do we have for', 'how much stock for', 'what is the current stock of', 'what is the stock of', 'current stock of', 'stock of product', 'stock of']:
            if pfx in target:
                target = target.split(pfx, 1)[1].strip()
                break
        target = target.rstrip('?.')
        res = database.list_products(search=target, is_active=True, conn=cat_conn)
        items = res["items"]

        if not items:
            speak_text = f"Boss, no product matching '{target}' was found in the catalogue."
            return {
                "speak": speak_text,
                "display": f"Stock: No match for '{target}'",
                "action": "catalogue_stock",
                "source": "Product Catalogue",
                "source_type": "catalogue",
                "match_count": 0,
                "follow_ups": ["What are all products?"]
            }
        elif len(items) > 1:
            candidates = ", ".join([f"{p['name']} (SKU: {p['sku'] or 'N/A'})" for p in items[:3]])
            speak_text = f"Boss, multiple products match '{target}': {candidates}. Please clarify the exact SKU or name."
            return {
                "speak": speak_text,
                "display": f"Multiple Matches ({len(items)}): {candidates}",
                "action": "catalogue_stock",
                "source": "Product Catalogue",
                "source_type": "catalogue",
                "match_count": len(items),
                "candidates": items[:5],
                "follow_ups": [f"What is the stock of {p['name']}?" for p in items[:3]]
            }
        else:
            p = items[0]
            speak_text = f"Boss, current stock of {p['name']} is {p['quantity_on_hand']} {p['unit']}. Reorder threshold is {p['reorder_level']} {p['unit']}."
            return {
                "speak": speak_text,
                "display": f"{p['name']}: {p['quantity_on_hand']} {p['unit']} in stock (Reorder: {p['reorder_level']})",
                "action": "catalogue_stock",
                "source": "Inventory Balance",
                "source_type": "catalogue",
                "match_count": 1,
                "product": p,
                "follow_ups": [f"What is the selling price of {p['name']}?", "Show all products"]
            }

    # 1G. Specific Product Selling Price
    if any(k in c_lower for k in ['show the selling price of', 'what is the selling price of', 'selling price of', 'sale price of', 'retail price of']):
        target = c_lower
        for pfx in ['show the selling price of', 'what is the selling price of', 'selling price of', 'sale price of', 'retail price of']:
            if pfx in target:
                target = target.split(pfx, 1)[1].strip()
                break
        return _build_selling_price_response(target, cat_conn, source_label="Product Catalogue")

    # 1H. Specific Product Purchase Cost
    if any(k in c_lower for k in ['what is the purchase price of', 'purchase price of', 'cost price of', 'buy price of', 'purchase cost of']):
        target = c_lower
        for pfx in ['what is the purchase price of', 'purchase price of', 'cost price of', 'buy price of', 'purchase cost of']:
            if pfx in target:
                target = target.split(pfx, 1)[1].strip()
                break
        target = target.rstrip('?.')
        res = database.list_products(search=target, is_active=True, conn=cat_conn)
        items = res["items"]

        if not items:
            speak_text = f"Boss, no product matching '{target}' was found in the catalogue."
            return {
                "speak": speak_text,
                "display": f"Cost: No match for '{target}'",
                "action": "catalogue_price",
                "source": "Product Catalogue",
                "source_type": "catalogue",
                "match_count": 0
            }
        elif len(items) > 1:
            candidates = ", ".join([f"{p['name']} (SKU: {p['sku'] or 'N/A'})" for p in items[:3]])
            speak_text = f"Boss, multiple products match '{target}': {candidates}. Please clarify the exact SKU or name."
            return {
                "speak": speak_text,
                "display": f"Multiple matches for '{target}'",
                "action": "catalogue_price",
                "source": "Product Catalogue",
                "source_type": "catalogue",
                "match_count": len(items),
                "candidates": items[:5]
            }
        else:
            p = items[0]
            speak_text = f"Boss, the purchase price of {p['name']} is {p['purchase_price']} {p['currency']}. Current selling price is {p['selling_price']} {p['currency']}."
            return {
                "speak": speak_text,
                "display": f"{p['name']}: Cost = ₹{p['purchase_price']:,.2f} | Selling = ₹{p['selling_price']:,.2f}",
                "action": "catalogue_price",
                "source": "Product Catalogue",
                "source_type": "catalogue",
                "match_count": 1,
                "product": p
            }

    # 1I. Find Product by Name or SKU
    if any(k in c_lower for k in ['find product', 'search product', 'lookup product', 'find sku', 'search sku']):
        target = c_lower
        for pfx in ['find product sku', 'search product sku', 'find product', 'search product', 'lookup product', 'find sku', 'search sku']:
            if pfx in target:
                target = target.split(pfx, 1)[1].strip()
                break
        return _build_find_product_response(target, cat_conn, source_label="Product Catalogue")

    # =========================================================================
    # 2. DATASET-AWARE NATURAL LANGUAGE QUERIES
    # =========================================================================

    is_dataset_query = any(k in c_lower for k in [
        'summarise this dataset', 'summarize this dataset', 'summarise dataset', 'summarize dataset',
        'how many rows and columns', 'rows and columns', 'how many rows', 'how many columns', 'row count', 'column count',
        'list all column names', 'list all columns', 'what are the columns', 'show columns', 'column names', 'list columns',
        'missing values in each column', 'missing values in this dataset', 'what are the missing values', 'missing values',
        'are there duplicate rows', 'duplicate rows', 'check duplicates', 'count duplicate records', 'duplicates in dataset',
        'show the first 10 rows', 'show first 10 rows', 'first 10 rows', 'preview rows', 'sample rows', 'first 5 rows',
        'average value of', 'average of', 'mean of', 'highest and lowest values', 'max and min of', 'max value of', 'min value of',
        'filter rows where', 'filter by', 'show rows where', 'rows where',
        'group by', 'count by', 'count records in',
        'which columns appear to contain dates', 'date columns', 'detect dates',
        'what data is missing', 'what data-quality problems', 'data quality problems', 'data quality', 'quality score', 'quality audit'
    ])

    if is_dataset_query:
        # Resolve dataset target
        target_ds_id, disambig = get_effective_dataset_id(cmd, context=context, db_path=db_path)
        if disambig:
            return disambig

        if not target_ds_id:
            msg = "Boss, no dataset is currently active. You can upload an Excel (.xlsx) or PDF file in the Data Import Protocol panel, or select a saved dataset from the Saved Data Library."
            return {
                "speak": msg,
                "display": "No active dataset loaded.",
                "action": "dataset_no_data",
                "source": "Dataset Intelligence",
                "source_type": "dataset",
                "follow_ups": ["Upload Excel File", "Show Saved Datasets", "What are all products?"]
            }

        # 2A. Dataset Dimensions (rows and columns)
        if any(k in c_lower for k in ['how many rows and columns', 'rows and columns', 'how many rows', 'how many columns', 'row count', 'column count', 'dataset dimensions']):
            try:
                res = dataset_intelligence.get_dataset_dimensions(target_ds_id, db_path=db_path)
                return {
                    "speak": f"Boss, {res['summary_text']}",
                    "display": f"{res['filename']}: {res.get('row_count', 0)} Rows × {res.get('column_count', 0)} Columns",
                    "action": "dataset_dimensions",
                    "source": f"Dataset: {res['filename']}",
                    "source_type": "dataset",
                    "dataset_id": target_ds_id,
                    "data": res,
                    "follow_ups": ["List all column names", "What are the missing values in each column?", "Summarise this dataset"]
                }
            except Exception as e:
                logger.error(f"Error computing dimensions: {e}")
                return {"speak": f"Boss, could not compute dimensions: {e}", "display": str(e), "action": "error"}

        # 2B. Summarize Dataset
        if any(k in c_lower for k in ['summarise this dataset', 'summarize this dataset', 'summarise dataset', 'summarize dataset', 'dataset summary', 'tell me about this dataset']):
            try:
                res = dataset_intelligence.summarize_dataset(target_ds_id, db_path=db_path)
                return {
                    "speak": res["speak"],
                    "display": res["display"],
                    "action": "dataset_summary",
                    "source": f"Dataset: {res['filename']}",
                    "source_type": "dataset",
                    "dataset_id": target_ds_id,
                    "data": res,
                    "follow_ups": ["List all column names", "What are the missing values in each column?", "Show the first 10 rows"]
                }
            except Exception as e:
                return {"speak": f"Boss, error summarizing dataset: {e}", "display": str(e), "action": "error"}

        # 2C. List Columns
        if any(k in c_lower for k in ['list all column names', 'list all columns', 'what are the columns', 'show columns', 'column names', 'list columns']):
            try:
                res = dataset_intelligence.list_dataset_columns(target_ds_id, db_path=db_path)
                rows = [{"column": c["name"], "type": c["inferred_type"], "non_null": c["non_null_count"], "missing": c["null_count"]} for c in res.get("column_details", [])]
                return {
                    "speak": res["speak"],
                    "display": res["display"],
                    "action": "dataset_columns",
                    "source": f"Dataset: {res['filename']}",
                    "source_type": "dataset",
                    "dataset_id": target_ds_id,
                    "columns": res["columns"],
                    "table": {"columns": ["COLUMN", "INFERRED TYPE", "NON-NULL COUNT", "MISSING COUNT"], "rows": rows},
                    "follow_ups": ["What are the missing values in each column?", "Show the first 10 rows"]
                }
            except Exception as e:
                return {"speak": f"Boss, error listing columns: {e}", "display": str(e), "action": "error"}

        # 2D. Missing Values
        if any(k in c_lower for k in ['what are the missing values', 'missing values in each column', 'missing values', 'missing data', 'null values', 'empty cells']):
            try:
                res = dataset_intelligence.get_missing_values(target_ds_id, db_path=db_path)
                rows = [{"column": c["column"], "missing_count": c["missing_count"], "missing_pct": f"{c['missing_pct']}%"} for c in res.get("top_missing_columns", [])]
                return {
                    "speak": res["speak"],
                    "display": res["display"],
                    "action": "dataset_missing_values",
                    "source": f"Dataset: {res['filename']}",
                    "source_type": "dataset",
                    "dataset_id": target_ds_id,
                    "total_missing": res.get("total_missing_cells", 0),
                    "table": {"columns": ["COLUMN", "MISSING CELLS", "MISSING %"], "rows": rows},
                    "follow_ups": ["Are there duplicate rows?", "Summarise this dataset"]
                }
            except Exception as e:
                return {"speak": f"Boss, error inspecting missing values: {e}", "display": str(e), "action": "error"}

        # 2E. Duplicate Rows
        if any(k in c_lower for k in ['are there duplicate rows', 'duplicate rows', 'check duplicates', 'count duplicate records', 'duplicates in dataset']):
            try:
                res = dataset_intelligence.get_duplicate_rows(target_ds_id, db_path=db_path)
                return {
                    "speak": res["speak"],
                    "display": res["display"],
                    "action": "dataset_duplicates",
                    "source": f"Dataset: {res['filename']}",
                    "source_type": "dataset",
                    "dataset_id": target_ds_id,
                    "data": res,
                    "follow_ups": ["What are the missing values in each column?", "Summarise this dataset"]
                }
            except Exception as e:
                return {"speak": f"Boss, error checking duplicate rows: {e}", "display": str(e), "action": "error"}

        # 2F. First N Rows
        if any(k in c_lower for k in ['show the first 10 rows', 'show first 10 rows', 'first 10 rows', 'preview rows', 'sample rows', 'first 5 rows']):
            n = 5 if '5' in c_lower else 10
            try:
                res = dataset_intelligence.get_head_rows(target_ds_id, n=n, db_path=db_path)
                return {
                    "speak": res["speak"],
                    "display": res["display"],
                    "action": "dataset_head",
                    "source": f"Dataset: {res['filename']}",
                    "source_type": "dataset",
                    "dataset_id": target_ds_id,
                    "table": {"columns": res.get("columns", [])[:8], "rows": res.get("rows", [])},
                    "follow_ups": ["List all column names", "Summarise this dataset"]
                }
            except Exception as e:
                return {"speak": f"Boss, error fetching rows: {e}", "display": str(e), "action": "error"}

        # 2G. Date Columns Detection
        if any(k in c_lower for k in ['which columns appear to contain dates', 'date columns', 'detect dates']):
            try:
                res = dataset_intelligence.detect_date_columns(target_ds_id, db_path=db_path)
                return {
                    "speak": res["speak"],
                    "display": res["display"],
                    "action": "dataset_dates",
                    "source": f"Dataset: {res['filename']}",
                    "source_type": "dataset",
                    "dataset_id": target_ds_id,
                    "date_columns": res.get("date_columns", []),
                    "follow_ups": ["List all column names", "Summarise this dataset"]
                }
            except Exception as e:
                return {"speak": f"Boss, error checking date columns: {e}", "display": str(e), "action": "error"}

        # 2H. Column Statistics (Average, Min, Max)
        if any(k in c_lower for k in ['average value of', 'average of', 'mean of', 'highest and lowest values', 'max and min of', 'max value of', 'min value of']):
            # Extract target column name
            col_target = c_lower
            for pfx in ['what is the average value of', 'what is the average of', 'average value of', 'average of', 'mean of', 'highest and lowest values of', 'highest and lowest values in', 'max and min of', 'max value of', 'min value of']:
                if pfx in col_target:
                    col_target = col_target.split(pfx, 1)[1].strip()
                    break
            col_target = col_target.rstrip('?.')

            try:
                res = dataset_intelligence.get_column_statistics(target_ds_id, col_target, db_path=db_path)
                return {
                    "speak": res["speak"],
                    "display": res["display"],
                    "action": "dataset_stats",
                    "source": f"Dataset: {res['filename']}",
                    "source_type": "dataset",
                    "dataset_id": target_ds_id,
                    "data": res,
                    "follow_ups": ["List all column names", "Summarise this dataset"]
                }
            except ValueError as ve:
                return {
                    "speak": f"Boss, {ve}",
                    "display": str(ve),
                    "action": "dataset_stats_error",
                    "source": "Dataset Intelligence",
                    "source_type": "dataset"
                }

        # 2I. Filter Rows
        if any(k in c_lower for k in ['filter rows where', 'filter by', 'show rows where']):
            # Pattern: filter rows where [col] equals [val]
            m = re.search(r'where ([\w\s_-]+) (equals|==|contains|>|<|>=|<=) ([\w\s\.-]+)', c_lower)
            if not m:
                m = re.search(r'where ([\w\s_-]+) is ([\w\s\.-]+)', c_lower)
                if m:
                    col_name = m.group(1).strip()
                    op = "equals"
                    val = m.group(2).strip()
                else:
                    return {
                        "speak": "Boss, please format your filter as: 'Filter rows where [column] equals [value]'.",
                        "display": "Invalid filter format. Example: Filter rows where Status equals Active",
                        "action": "dataset_filter_error",
                        "source": "Dataset Intelligence",
                        "source_type": "dataset"
                    }
            else:
                col_name = m.group(1).strip()
                op = m.group(2).strip()
                val = m.group(3).strip()

            try:
                res = dataset_intelligence.filter_dataset(target_ds_id, col_name, op, val, db_path=db_path)
                return {
                    "speak": res["speak"],
                    "display": res["display"],
                    "action": "dataset_filter",
                    "source": f"Dataset: {res['filename']}",
                    "source_type": "dataset",
                    "dataset_id": target_ds_id,
                    "match_count": res.get("match_count", 0),
                    "table": {"columns": res.get("columns", [])[:8], "rows": res.get("rows", [])},
                    "follow_ups": ["Summarise this dataset", "Show the first 10 rows"]
                }
            except ValueError as ve:
                return {"speak": f"Boss, {ve}", "display": str(ve), "action": "dataset_filter_error"}

        # 2J. Group By
        if any(k in c_lower for k in ['group by', 'count by']):
            m = re.search(r'(?:group by|count by)\s+([\w\s_-]+)', c_lower)
            if m:
                col_name = m.group(1).replace('and count records', '').replace('and count', '').strip().rstrip('?.')
                try:
                    res = dataset_intelligence.group_by_column(target_ds_id, col_name, db_path=db_path)
                    rows = [{"group": g["group"], "count": g["count"]} for g in res.get("groups", [])]
                    return {
                        "speak": res["speak"],
                        "display": res["display"],
                        "action": "dataset_group",
                        "source": f"Dataset: {res['filename']}",
                        "source_type": "dataset",
                        "dataset_id": target_ds_id,
                        "table": {"columns": ["CATEGORY / GROUP", "RECORD COUNT"], "rows": rows},
                        "follow_ups": ["Summarise this dataset", "List all column names"]
                    }
                except ValueError as ve:
                    return {"speak": f"Boss, {ve}", "display": str(ve), "action": "dataset_group_error"}

        # 2K. Data Quality Audit
        # 2K. Data Quality Audit & Missing Data Summary
        if any(k in c_lower for k in ['what data is missing', 'what data-quality problems', 'data quality problems', 'data quality', 'quality score', 'quality audit']):
            try:
                bi_rep = context.get("current_bi_report")
                if not bi_rep and target_ds_id:
                    rep = database.get_latest_report_for_dataset(target_ds_id, db_path=db_path)
                    if rep and rep.get("report_content"):
                        bi_rep = rep.get("report_content")

                if bi_rep and bi_rep.get("data_quality"):
                    dq = bi_rep["data_quality"]
                    score = dq.get("score", 100)
                    issues = dq.get("issues", [])
                    speak_text = f"Boss, data quality score is {score} percent with {len(issues)} issues detected."
                    return {
                        "speak": speak_text,
                        "display": f"Data Quality: {score}% ({len(issues)} anomalies)",
                        "action": "bi_quality",
                        "source": f"Dataset: {bi_rep.get('file_name', 'active')}",
                        "source_type": "dataset",
                        "issues": issues[:10],
                        "data_quality": dq,
                        "follow_ups": ["What are the missing values in each column?", "Summarise this dataset"]
                    }
                else:
                    res = dataset_intelligence.summarize_dataset(target_ds_id, db_path=db_path)
                    speak_text = f"Boss, data quality overview for {res['filename']}: {res['missing_pct']}% missing cells and {res['duplicate_rows']} duplicate rows."
                    return {
                        "speak": speak_text,
                        "display": f"Quality: {res['missing_pct']}% missing, {res['duplicate_rows']} duplicates",
                        "action": "bi_quality",
                        "source": f"Dataset: {res['filename']}",
                        "source_type": "dataset"
                    }
            except Exception as e:
                return {"speak": f"Boss, error retrieving quality report: {e}", "display": str(e), "action": "error"}

    # =========================================================================
    # 3. EXISTING BUSINESS INTELLIGENCE REPORTS & DOSSIERS
    # =========================================================================

    if any(k in c_lower for k in ['analyze this file', 'complete report', 'bi report', 'business report', 'full report']) or (c_lower == 'report'):
        bi_rep = context.get("current_bi_report")
        if not bi_rep:
            # Check latest dataset report in DB
            ds_res = database.list_datasets(page=1, page_size=1, db_path=db_path)
            latest_ds = ds_res.get("datasets") or ds_res.get("items") or []
            if latest_ds:
                rep_record = database.get_latest_report_for_dataset(latest_ds[0]["id"], db_path=db_path)
                if rep_record:
                    bi_rep = rep_record.get("report_content")

        if not bi_rep:
            msg = "No business intelligence dataset has been analyzed yet, Boss. Please upload an Excel or PDF document first."
            return {"speak": msg, "display": msg, "action": "bi_no_data", "source": "BI Engine", "source_type": "report"}

        fn = bi_rep.get("file_name", "document")
        cls_name = bi_rep.get("classification", {}).get("detected_type", "General Tabular")
        q_score = bi_rep.get("data_quality", {}).get("score", "N/A")
        insights_count = len(bi_rep.get("insights", []))

        speak_text = f"Boss, here is the intelligence synthesis for {fn}. It is classified as {cls_name} with an overall data quality score of {q_score} percent and {insights_count} analytical findings."
        return {
            "speak": speak_text,
            "display": f"REPORT: {fn} | Type: {cls_name} | Quality: {q_score}% | Insights: {insights_count}",
            "action": "bi_report_summary",
            "source": f"Report: {fn}",
            "source_type": "report",
            "report": bi_rep,
            "follow_ups": ["Explain the findings", "Highest margin products", "Summarise this dataset"]
        }

    # 3B. Highest Margin / Pricing Analysis
    if any(k in c_lower for k in ['highest margin', 'highest margins', 'margin', 'pricing and margins', 'profitability', 'profit margin']):
        bi_rep = context.get("current_bi_report")
        if not bi_rep:
            ds_res = database.list_datasets(page=1, page_size=1, db_path=db_path)
            latest_ds = ds_res.get("datasets") or ds_res.get("items") or []
            if latest_ds:
                rep_record = database.get_latest_report_for_dataset(latest_ds[0]["id"], db_path=db_path)
                if rep_record:
                    bi_rep = rep_record.get("report_content")

        if not bi_rep:
            msg = "No dataset loaded, Boss. Please upload product pricing data first."
            return {"speak": msg, "display": msg, "action": "bi_no_data", "source": "BI Engine", "source_type": "report"}

        pricing = bi_rep.get("pricing", {})
        if not pricing.get("computed"):
            missing = ", ".join(pricing.get("missing_fields", ["Cost Price", "Selling Price"]))
            speak_text = f"Pricing and margin metrics cannot be computed, Boss. The required fields ({missing}) are missing from this dataset."
            return {"speak": speak_text, "display": speak_text, "action": "bi_pricing_unavailable", "source": "BI Pricing", "source_type": "report"}

        top_p = pricing.get("highest_margin_products", [])
        avg_m = pricing.get("average_gross_margin_pct", 0)
        leader = top_p[0] if top_p else None
        if leader:
            speak_text = f"Boss, the highest gross margin product is {leader['product']} at {leader['gross_margin_pct']} percent margin. The average gross margin is {avg_m} percent."
        else:
            speak_text = f"Boss, average gross margin is {avg_m} percent across available pricing records."

        return {
            "speak": speak_text,
            "display": f"Avg Margin: {avg_m}% | Top: {leader['product'] if leader else 'N/A'}",
            "action": "bi_pricing",
            "source": "Commercial Intelligence",
            "source_type": "report",
            "pricing": pricing,
            "follow_ups": ["Show all products", "Check inventory summary"]
        }

    # 3C. Inventory Telemetry & Low Stock Status
    if any(k in c_lower for k in ['low stock status', 'inventory status', 'bi inventory', 'stock status']):
        bi_rep = context.get("current_bi_report")
        if not bi_rep:
            ds_res = database.list_datasets(page=1, page_size=1, db_path=db_path)
            latest_ds = ds_res.get("datasets") or ds_res.get("items") or []
            if latest_ds:
                rep_record = database.get_latest_report_for_dataset(latest_ds[0]["id"], db_path=db_path)
                if rep_record:
                    bi_rep = rep_record.get("report_content")

        if not bi_rep:
            msg = "No dataset loaded, Boss. Please upload product inventory data first."
            return {"speak": msg, "display": msg, "action": "bi_no_data", "source": "BI Engine", "source_type": "report"}

        inv = bi_rep.get("inventory", {})
        if not inv.get("computed"):
            missing = ", ".join(inv.get("missing_fields", ["Quantity / Stock"]))
            speak_text = f"Inventory metrics cannot be computed, Boss. The required fields ({missing}) are missing from this dataset."
            return {"speak": speak_text, "display": speak_text, "action": "bi_inventory_unavailable", "source": "BI Inventory", "source_type": "report"}

        low_items = inv.get("low_stock_items", [])
        total_units = inv.get("total_units", 0)
        speak_text = f"Boss, recorded inventory total is {total_units} units. {len(low_items)} items are flagged for low stock or reorder."
        return {
            "speak": speak_text,
            "display": f"Inventory: {total_units} units | {len(low_items)} low-stock alerts",
            "action": "bi_inventory",
            "source": "Inventory Analytics",
            "source_type": "report",
            "inventory": inv,
            "low_stock_items": low_items,
            "follow_ups": ["Show all products", "Which products are low in stock?"]
        }

    # 3D. Sales Trends
    if any(k in c_lower for k in ['sales trends', 'sales trend', 'revenue', 'sales revenue', 'sales analysis']):
        bi_rep = context.get("current_bi_report")
        if not bi_rep:
            ds_res = database.list_datasets(page=1, page_size=1, db_path=db_path)
            latest_ds = ds_res.get("datasets") or ds_res.get("items") or []
            if latest_ds:
                rep_record = database.get_latest_report_for_dataset(latest_ds[0]["id"], db_path=db_path)
                if rep_record:
                    bi_rep = rep_record.get("report_content")

        if not bi_rep:
            msg = "No dataset loaded, Boss. Please upload sales records first."
            return {"speak": msg, "display": msg, "action": "bi_no_data", "source": "BI Engine", "source_type": "report"}

        sales = bi_rep.get("sales", {})
        if not sales.get("computed"):
            missing = ", ".join(sales.get("missing_fields", ["Sales Amount / Revenue"]))
            speak_text = f"Sales analytics cannot be computed, Boss. The dataset is missing required sales columns ({missing})."
            return {"speak": speak_text, "display": speak_text, "action": "bi_sales_unavailable", "source": "BI Sales", "source_type": "report"}

        rev = sales.get("total_revenue", 0)
        tx = sales.get("transaction_count", 0)
        atv = sales.get("average_transaction_value", 0)
        speak_text = f"Boss, total recorded sales revenue is {rev:,.2f} across {tx} transactions, averaging {atv:,.2f} per transaction."
        return {
            "speak": speak_text,
            "display": f"Revenue: ₹{rev:,.2f} | Transactions: {tx} | ATV: ₹{atv:,.2f}",
            "action": "bi_sales",
            "source": "Sales Analytics",
            "source_type": "report",
            "sales": sales
        }

    # 3D. Key Findings
    if any(k in c_lower for k in ['findings', 'top findings', 'insights', 'explain the findings', 'key findings']):
        bi_rep = context.get("current_bi_report")
        if not bi_rep:
            ds_res = database.list_datasets(page=1, page_size=1, db_path=db_path)
            latest_ds = ds_res.get("datasets") or ds_res.get("items") or []
            if latest_ds:
                rep_record = database.get_latest_report_for_dataset(latest_ds[0]["id"], db_path=db_path)
                if rep_record:
                    bi_rep = rep_record.get("report_content")

        if not bi_rep:
            msg = "No findings available, Boss. Please upload and analyze a dataset first."
            return {"speak": msg, "display": msg, "action": "bi_no_data", "source": "BI Engine", "source_type": "report"}

        insights = bi_rep.get("insights", [])
        if not insights:
            speak_text = "Boss, no anomalous or noteworthy insights were triggered by this dataset."
        else:
            first_two = [f"{i['title']}: {i['explanation']}" for i in insights[:2]]
            speak_text = "Boss, here are the top findings: " + " Furthermore, ".join(first_two)

        return {
            "speak": speak_text,
            "display": f"Key Insights: {len(insights)} identified",
            "action": "bi_insights",
            "source": "Synthesized Insights",
            "source_type": "report",
            "insights": insights
        }

    # =========================================================================
    # 4. GENERAL ASSISTANT / PROTOCOL COMMANDS
    # =========================================================================

    now = datetime.datetime.now()

    if 'joke' in c_lower:
        joke = pyjokes.get_joke()
        return {"speak": joke, "display": joke, "action": "joke", "source": "Humor Protocol", "source_type": "system"}

    if 'time' in c_lower:
        t = now.strftime("%I:%M %p")
        return {"speak": f"Boss, the current time is {t}", "display": t, "action": "time", "source": "System Chronometer", "source_type": "system"}

    if 'date' in c_lower or 'today' in c_lower or 'day' in c_lower:
        d = now.strftime("%A, %B %d, %Y")
        return {"speak": f"Boss, today is {d}", "display": d, "action": "date", "source": "System Chronometer", "source_type": "system"}

    if any(q in c_lower for q in ['who are you', 'your name', 'what can you do', 'what is jarvis']):
        speak_text = "I am J.A.R.V.I.S., your personal AI business intelligence assistant. I manage local product catalogues, real-time stock balances, tabular dataset analytics, and executive business reports."
        return {"speak": speak_text, "display": speak_text, "action": "intro", "source": "J.A.R.V.I.S. Identity", "source_type": "system"}

    if any(q in c_lower for q in ['system', 'cpu', 'battery', 'condition', 'power']):
        usage = psutil.cpu_percent(interval=None) if hasattr(psutil, 'cpu_percent') else 15.0
        batt_str = ""
        if hasattr(psutil, 'sensors_battery'):
            b = psutil.sensors_battery()
            if b:
                batt_str = f" Battery level is at {b.percent} percent."
        speak_text = f"Boss, CPU is running at {usage} percent.{batt_str} All quantum core matrices are stable."
        return {"speak": speak_text, "display": speak_text, "action": "system", "source": "System Telemetry", "source_type": "system"}

    if 'play' in c_lower or 'youtube' in c_lower:
        search_query = c_lower.replace('play', '').replace('youtube', '').replace('a song', '').strip()
        yt_url = f"https://www.youtube.com/results?search_query={requests.utils.quote(search_query)}"
        return {"speak": f"Accessing YouTube protocols for {search_query}.", "display": f"Playing: {search_query}", "action": "youtube", "url": yt_url, "source": "Media Matrix", "source_type": "system"}

    if 'wikipedia' in c_lower:
        query = c_lower.replace('wikipedia', '').replace('search', '').replace('tell me about', '').strip()
        try:
            summary = wikipedia.summary(query, sentences=2)
            return {"speak": summary, "display": summary, "action": "wikipedia", "source": "Wikipedia Archive", "source_type": "system"}
        except Exception:
            return {"speak": f"Could not retrieve Wikipedia archives for {query}.", "display": "Topic not found or too broad.", "action": "wikipedia_error", "source": "Wikipedia", "source_type": "system"}

    if 'covid' in c_lower or 'coronavirus' in c_lower:
        req_state = c_lower.replace('covid', '').replace('in', '').replace('cases', '').replace('check', '').strip() or 'delhi'
        from state import state as state_map
        matched_state = "Delhi"
        for k, v in state_map.items():
            if k in req_state:
                matched_state = v
                break
        return {"speak": f"Boss, querying COVID telemetry for {matched_state}.", "display": f"State: {matched_state}", "action": "covid", "state": matched_state, "source": "COVID Telemetry", "source_type": "system"}

    if 'contact' in c_lower or 'phone' in c_lower:
        return {"speak": "Accessing local communications directory.", "display": "Displaying Contacts list.", "action": "contacts", "source": "Contacts Directory", "source_type": "system"}

    if 'news' in c_lower:
        return {"speak": "Loading today's top tech intelligence headlines.", "display": "News Protocol active.", "action": "news", "source": "Tech News Matrix", "source_type": "system"}

    # =========================================================================
    # 5. GENERAL INQUIRIES & HELPFUL GUIDANCE (Replacing Blind Fallback)
    # =========================================================================

    # If the user asks about available capabilities or an unsupported question
    speak_text = (
        f"Boss, I processed your query: '{cmd}'. You can ask me to list catalogue products, "
        f"check stock and pricing, summarize active datasets, audit data quality, or review business reports."
    )
    return {
        "speak": speak_text,
        "display": f"Tactical Order Standby: '{cmd}'",
        "action": "assistant_help",
        "source": "J.A.R.V.I.S. Core",
        "source_type": "system",
        "follow_ups": [
            "What are all products?",
            "Which products are low in stock?",
            "Summarise this dataset",
            "What are the missing values in each column?",
            "Explain the findings"
        ]
    }
