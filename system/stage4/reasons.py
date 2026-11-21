"""Templated reasons. Two to four sentences, this hit's own facts, no model prose."""

from __future__ import annotations

from stage4.model import AGREE, Decision


def _sentence(text: str) -> str:
    text = " ".join(str(text).split())
    if not text:
        return ""
    if text[-1] not in ".!?":
        text += "."
    return text


def render(decision: Decision, hit: dict, person: dict, alert: dict) -> str:
    parts = [_sentence(item) for item in _parts(decision, hit, person, alert)]
    parts = [item for item in parts if item]
    anchor = _sentence(_anchor(decision, hit, person, alert))
    hit_id = str(hit.get("hit_id") or "")
    if anchor and hit_id and hit_id not in " ".join(parts):
        parts.append(anchor)
    if len(parts) == 1:
        parts.append(_sentence(_closer(decision, hit)))
    if len(parts) > 4 and anchor in parts:
        parts = [item for item in parts if item != anchor][:3] + [anchor]
    return " ".join(parts[:4])


def _closer(decision: Decision, hit: dict) -> str:
    name = _hit_name(hit)
    hit_id = hit.get("hit_id") or "this hit"
    if decision.decision == "DIFFERENT_ENTITY":
        return f"That contradiction is enough to treat {name} ({hit_id}) as a different entity"
    if decision.decision == "SAME_ENTITY":
        return f"Nothing in the records contradicts that {name} ({hit_id}) is the customer"
    if decision.missing:
        return f"{name} ({hit_id}) is left for review because {decision.missing}"
    return f"{name} ({hit_id}) is left for review"


def _anchor(decision: Decision, hit: dict, person: dict, alert: dict) -> str:
    """One sentence that only this hit can share: names, the hit id, and cited records."""
    customer = _customer_name(person, alert)
    listed = _hit_name(hit)
    hit_id = hit.get("hit_id") or "unknown hit"
    record = decision.record or "none"
    cited = ", ".join(decision.evidence) if decision.evidence else (alert.get("alert_id") or hit_id)
    gaps = list(getattr(decision, "screened_gaps", None) or [])
    gap = f", missing screened field {', '.join(gaps)}" if gaps else ""
    return (
        f"The names compared are {customer} and {listed} ({hit_id}), "
        f"customer record {record}, records cited {cited}{gap}"
    )


def _parts(decision: Decision, hit: dict, person: dict, alert: dict) -> list[str]:
    cmp = decision.cmp
    if decision.kind == "not_found_clear":
        screened = ((alert.get("customer") or {}).get("entity_type") or "customer")
        listed = hit.get("entity_type") or "listed entity"
        return [
            f"The alert was screened as { _article(screened) } but the hit is { _article(listed) }",
            "No customer record was found, and the entity types alone contradict",
        ]
    if decision.kind == "not_found_review":
        screened = _customer_name(person, alert)
        listed = _hit_name(hit)
        alert_id = alert.get("alert_id") or "this alert"
        return [
            f"No customer record fits the screened name {screened} on {alert_id}, so {listed} ({hit.get('hit_id')}) cannot be compared with a customer",
            f"{listed} is left for review",
        ]
    if decision.kind == "not_decided":
        return [
            "This hit could not be decided because a required profile or alert resolution is missing",
            "The hit is left for review and the alert cannot be cleared",
        ]
    if decision.kind == "ambiguous_split":
        return [decision.gate_note or "More than one customer fits this alert and they do not agree, so the hit is left for review",
                "The customer record is ambiguous"]
    if decision.kind == "ambiguous_review":
        return [decision.gate_note or "More than one customer fits this alert",
                "For each of them the records do not settle the hit, so it can be neither cleared nor confirmed"]
    if cmp is None:
        return ["The records do not settle this hit", "It is left for review"]

    if decision.decision == "DIFFERENT_ENTITY":
        sentences = [_ground(code, cmp, hit, person, alert) for code in decision.passed]
        return sentences
    if decision.kind == "review_gate":
        return [
            _ground(decision.fired[0], cmp, hit, person, alert),
            f"However, {decision.gate_note}, so the hit is left for review",
        ]
    if decision.decision == "SAME_ENTITY":
        return _same_parts(decision.reason_code, cmp, hit, person)
    agreeing = _agreeing_bits(cmp, hit, person)
    tail = decision.missing or "the records do not settle the comparison"
    if agreeing:
        return agreeing + [f"Nothing in the customer's records contradicts the hit, and {tail}, so the hit can be neither cleared nor confirmed"]
    return [
        f"Nothing in the customer's records contradicts the hit, and {tail}",
        "The hit can be neither cleared nor confirmed",
    ]


def _same_parts(code: str, cmp, hit: dict, person: dict) -> list[str]:
    dob = _dob_sentence(cmp, person)
    name = _name_sentence(cmp)
    shared = ", ".join(cmp.location.detail.get("shared") or [])
    if code == "NAME_DOB_LOCATION_MATCH":
        return [dob, f"Both the customer and the hit are linked to {shared}", name]
    if code == "NAME_DOB_MATCH":
        if not (cmp.location.hit or []):
            country = "The hit gives no country to compare"
        else:
            country = "The customer has no country on record"
        return [dob, name, country]
    return [f"Both the customer and the hit are linked to {shared}", name, "Nothing in the dates contradicts that match"]


def _ground(code: str, cmp, hit: dict, person: dict, alert: dict) -> str:
    if code == "ENTITY_TYPE_MISMATCH":
        customer = cmp.entity_type.customer or "unknown"
        listed = cmp.entity_type.hit or "unknown"
        source = (cmp.entity_type.sources or [None])[0]
        where = f" ({source})" if source else ""
        return f"The customer is {_article(str(customer))}{where} but the hit is {_article(str(listed))}"
    if code == "DECEASED":
        death = cmp.death.hit or "an unknown date"
        screened = alert.get("screened_at") or cmp.death.customer or "the screening date"
        return f"The hit's profile gives a date of death of {death}, before the customer was screened on {str(screened)[:10]}"
    if code == "TEMPORAL_IMPOSSIBILITY":
        if cmp.person_type == "Company":
            inc = cmp.time.customer or "an unknown date"
            source = (cmp.time.sources or ["the customer record"])[0]
            return (
                f"The customer was incorporated on {inc} ({source}), after the hit's profile reports activity on {cmp.time.detail.get('report')}"
            )
        year = str(cmp.time.customer or "")[:4]
        source = (cmp.time.sources or ["the customer record"])[0]
        age = cmp.time.detail.get("max_age")
        age_text = str(age) if age is not None else "under 16"
        return (
            f"The customer was born in {year} ({source}), so they were at most {age_text} when the hit's profile reports activity on {cmp.time.detail.get('report')}"
        )
    if code == "DOB_MISMATCH":
        dob = cmp.dob.customer or "unknown"
        source = (cmp.dob.sources or ["the customer record"])[0]
        phrase = cmp.dob.detail.get("phrase") or (
            f"the hit's date of birth is {cmp.dob.hit}" if cmp.dob.hit else "the hit gives a different date of birth"
        )
        return f"The customer's date of birth is {dob} ({source}) but {phrase}"
    if code == "NAME_MISMATCH_VERIFIED":
        legal = (person.get("legal_name") or {}).get("value") or cmp.name.customer
        source = (cmp.name.sources or ["the customer record"])[0]
        listed = _primary_name(hit) or cmp.name.hit or "the listed name"
        return f"The customer's verified name is {legal} ({source}), which does not match the hit's name {listed}"
    countries = ", ".join(cmp.location.customer or []) or "no country"
    listed = ", ".join(cmp.location.hit or []) or "no country"
    sources = ", ".join(cmp.location.sources) if cmp.location.sources else "the customer records"
    hit_id = hit.get("hit_id") or "the hit"
    return (
        f"The customer is linked only to {countries} ({sources}) but the hit {hit_id} is linked only to {listed}"
    )


def _dob_sentence(cmp, person: dict) -> str:
    dob = cmp.dob.customer or (person.get("dob") or {}).get("value") or "unknown"
    source = ((person.get("dob") or {}).get("source_id")) or ((cmp.dob.sources or ["the customer record"])[0])
    hit_years = _hit_years(cmp)
    return f"The customer's date of birth {dob} ({source}) agrees with the hit's {hit_years}"


def _name_sentence(cmp) -> str:
    matched = cmp.name.detail.get("matched_hit_name") or cmp.name.hit or "the listed name"
    return f"The customer's name agrees with the hit's name {matched}"


def _hit_years(cmp) -> str:
    candidates = cmp.dob.detail.get("candidates") or []
    shown = []
    for candidate in candidates:
        years = list(candidate.get("years") or [])
        if len(years) == 2:
            shown.append(f"{years[0]} or {years[1]}")
        elif len(years) > 2:
            shown.append(f"{years[0]}-{years[-1]}")
        elif len(years) == 1 and candidate.get("month") and candidate.get("day"):
            shown.append(f"{years[0]:04d}-{int(candidate['month']):02d}-{int(candidate['day']):02d}")
        elif len(years) == 1 and candidate.get("month"):
            shown.append(f"{years[0]:04d}-{int(candidate['month']):02d}")
        elif len(years) == 1:
            shown.append(str(years[0]))
    return ", ".join(shown) or (cmp.dob.hit or "the listed date")


def _agreeing_bits(cmp, hit: dict, person: dict) -> list[str]:
    bits = []
    if cmp.dob.status == AGREE:
        bits.append(_dob_sentence(cmp, person))
    if cmp.location.status == AGREE:
        shared = ", ".join(cmp.location.detail.get("shared") or [])
        bits.append(f"Both the customer and the hit are linked to {shared}")
    if cmp.name.status == AGREE:
        bits.append(_name_sentence(cmp))
    return bits


def _hit_name(hit: dict) -> str:
    return _primary_name(hit) or hit.get("name") or "the listed name"


def _customer_name(person: dict, alert: dict) -> str:
    legal = (person.get("legal_name") or {}).get("value")
    if legal:
        return str(legal)
    screened = (alert.get("customer") or {}).get("name")
    return str(screened) if screened else "the screened customer"


def _primary_name(hit: dict) -> str | None:
    for entry in hit.get("names") or []:
        if entry.get("kind") == "primary" and entry.get("value"):
            return entry["value"]
    return None


def _article(kind: str) -> str:
    folded = kind.strip().lower()
    if folded == "company":
        return "a company"
    if folded == "individual":
        return "an individual"
    return f"a {kind}"
