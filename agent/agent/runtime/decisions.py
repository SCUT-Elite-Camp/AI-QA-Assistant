"""Native Agent control actions; these do not perform source IO."""
from agent.tools.argument_validation import parse_arguments, validate_arguments


def _schema(name, description, properties):
    return {"type":"function", "function":{"name":name, "description":description,
        "parameters":{"type":"object", "properties":properties,
                      "required":list(properties), "additionalProperties":False}}}


CONTROL_TOOLS = [
    _schema("prepare_answer", "Generate a grounded answer from the current evidence. No answer text here.", {}),
    _schema("ask_clarification", "Ask a necessary question about ambiguous user intent.",
            {"question":{"type":"string", "minLength":1, "maxLength":2000}}),
    _schema("report_insufficient", "End when the available sources cannot support an answer.",
            {"reason":{"type":"string", "minLength":1, "maxLength":2000}}),
]
CONTROL_NAMES = {tool["function"]["name"] for tool in CONTROL_TOOLS}


def parse_decision(calls):
    if len(calls) != 1:
        raise ValueError("control_action_must_be_alone")
    function = calls[0]["function"]
    name = function["name"]
    schema = next(tool["function"]["parameters"] for tool in CONTROL_TOOLS if tool["function"]["name"] == name)
    arguments = parse_arguments(function.get("arguments", {}))
    validate_arguments(schema, arguments)
    return {"action":{"prepare_answer":"answer", "ask_clarification":"clarify",
                      "report_insufficient":"insufficient"}[name], **arguments}
