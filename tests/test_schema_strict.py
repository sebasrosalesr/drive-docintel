from docintel.schema import Extraction, count_optional_and_union, extraction_json_schema


def test_schema_has_no_optional_or_union_fields():
    optional, union = count_optional_and_union(extraction_json_schema())
    assert optional <= 20 and union <= 12, (optional, union)
    assert (optional, union) == (0, 0)


def test_schema_forbids_extra_properties_everywhere():
    s = extraction_json_schema()
    assert s["additionalProperties"] is False
    for d in s["$defs"].values():
        assert d["additionalProperties"] is False


def test_round_trip():
    ex = Extraction.model_validate({"doc_type": "other", "title": "", "summary": "", "key_points": [], "manager": "", "manager_evidence": "", "as_of_date": "", "as_of_evidence": "", "currency": "", "funds": [], "metrics": [], "facts": [], "warnings": []})
    assert ex.doc_type == "other"
