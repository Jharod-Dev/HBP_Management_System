UNIT_STATUSES = ("AVAILABLE", "UNAVAILABLE")


def validate_unit_form(form, categories):
    errors = {}
    name = form.get("name", "").strip()
    description = form.get("description", "").strip()
    category_value = form.get("category_id", "").strip()

    if not name:
        errors["name"] = "Unit name is required."
    elif len(name) > 50:
        errors["name"] = "Unit name must be 50 characters or fewer."

    if len(description) > 255:
        errors["description"] = "Description must be 255 characters or fewer."

    try:
        category_id = int(category_value)
    except (TypeError, ValueError):
        category_id = None
        errors["category_id"] = "Select a valid category."

    category_ids = {category["id"] for category in categories}
    if category_id is not None and category_id not in category_ids:
        errors["category_id"] = "Select a valid category."

    status = form.get("status", "AVAILABLE").strip().upper()
    if status not in UNIT_STATUSES:
        errors["status"] = "Select a valid operational status."

    return errors, {
        "name": name,
        "description": description,
        "category_id": category_id,
        "status": status,
    }
