import pytest

from site_agent.brain import editor
from site_agent.hands.payload_gateway import PayloadContract, PayloadGatewayClient, PayloadGatewayError


def contract():
    fields = {
        "productAttributes": [{"name": name, "type": "relationship" if name == "product" else "text", "required": True} for name in ["product", "key", "label", "valueType", "valueText"]],
        "productVariants": [{"name": "sku", "type": "text", "required": True}, {"name": "product", "type": "relationship", "required": True}],
    }
    return {"enabled": {"collections": list(fields)}, "authoring": {"collections": fields}}


def plan(collection, identifier, identifier_kind, fields):
    return editor._validate_website_change_plan({"content_effects": [{
        "kind": "collection", "operation": "create", "collection": collection,
        "identifier": identifier, "identifier_kind": identifier_kind,
        "fields": fields, "summary": "Create the requested catalog record",
    }], "source_brief": ""}, contract())


def test_attribute_creates_match_exact_product_and_key_not_a_fabricated_route():
    fields = ["product", "key", "label", "valueType", "valueText"]
    context = {"_website_change_plan": plan("productAttributes", '["42", "material"]', "productKey", fields)}
    data = {"product": 42, "key": "material", "label": "Material", "valueType": "text", "valueText": "Cotton"}
    effect = editor._plan_effect_for_tool(context, "create_payload_draft", {"collection": "productAttributes", "data": data})
    assert effect["identifier"] == '["42","material"]'
    with pytest.raises(ValueError, match="exact target"):
        editor._plan_effect_for_tool(context, "create_payload_draft", {"collection": "productAttributes", "data": {**data, "product": 43}})


def test_variant_create_uses_sku_and_does_not_weaken_planned_field_scope():
    context = {"_website_change_plan": plan("productVariants", "SHIRT-M", "sku", ["product", "sku"])}
    assert editor._plan_effect_for_tool(context, "create_payload_draft", {"collection": "productVariants", "data": {"product": 42, "sku": "SHIRT-M"}})
    with pytest.raises(ValueError, match="must match the validated plan"):
        editor._plan_effect_for_tool(context, "create_payload_draft", {"collection": "productVariants", "data": {"product": 42, "sku": "SHIRT-M", "stock": 5}})
    with pytest.raises(ValueError, match="canonical"):
        plan("productVariants", "shirt", "slug", ["product", "sku"])


def test_gateway_preserves_canonical_camel_case_collection_identity():
    client = PayloadGatewayClient("https://tenant.test", "test-token", PayloadContract(frozenset(), "helloada-content-v4", "0.6.0", 10, "a" * 64))
    assert client._collection("productAttributes") == "productAttributes"
    assert client._collection("productvariants") == "productVariants"
    with pytest.raises(PayloadGatewayError, match="unsupported"):
        client._collection("orders")
