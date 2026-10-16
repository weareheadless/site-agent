import json

from site_agent.brain.growth import _response


class RecordingLLM:
    def __init__(self):
        self.kwargs = None

    def chat(self, messages, **kwargs):
        self.kwargs = kwargs
        return json.dumps({"summary": "Grounded review.", "opportunities": []})


def test_structured_growth_plans_disable_hidden_reasoning():
    llm = RecordingLLM()

    result = _response(
        {"llm": llm},
        "summary: nonempty string; opportunities: array.",
        {"stage": "assess", "maxRecommendations": 3},
    )

    assert result["summary"] == "Grounded review."
    assert llm.kwargs == {
        "json_mode": True,
        "temperature": 0.2,
        "enable_thinking": False,
    }
