//! Presentation rules for retained traces. The primary projection is redacted;
//! the original server response remains separately accessible by explicit action.
use serde_json::{Map, Value};

fn sensitive(key: &str) -> bool {
    let compact: String = key
        .chars()
        .filter(|c| c.is_ascii_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect();
    [
        "password",
        "passwd",
        "secret",
        "apikey",
        "apitoken",
        "accesstoken",
        "refreshtoken",
        "authorization",
        "cookie",
        "privatekey",
        "clientsecret",
        "sessiontoken",
        "credential",
        "bearer",
    ]
    .iter()
    .any(|word| compact.contains(*word))
}

fn sanitize_text(text: &str) -> String {
    let lower = text.to_ascii_lowercase();
    if lower.contains("-----begin")
        && (lower.contains("private key") || lower.contains("certificate"))
    {
        return "[redacted PEM material]".into();
    }
    if lower.contains("authorization:")
        || lower.contains("bearer ")
        || lower.contains("cookie:")
        || lower.contains("set-cookie:")
        || lower.contains("password=")
        || lower.contains("api_key=")
        || lower.contains("token=")
        || lower.contains("secret=")
    {
        return "[redacted potential credentials]".into();
    }
    text.to_owned()
}

pub fn sanitize(value: &Value) -> Value {
    match value {
        Value::Object(fields) => Value::Object(
            fields
                .iter()
                .map(|(key, value)| {
                    (
                        key.clone(),
                        if sensitive(key) {
                            Value::String("[redacted]".into())
                        } else {
                            sanitize(value)
                        },
                    )
                })
                .collect::<Map<_, _>>(),
        ),
        Value::Array(items) => Value::Array(items.iter().map(sanitize).collect()),
        Value::String(text) => Value::String(sanitize_text(text)),
        _ => value.clone(),
    }
}

pub fn capture_state(value: Option<&Value>, explicit: &str) -> &'static str {
    let explicit = explicit.to_ascii_lowercase();
    if explicit.contains("redact") || value.and_then(Value::as_str) == Some("<redacted>") {
        "Redacted"
    } else if explicit.contains("not_captured")
        || explicit.contains("missing")
        || explicit.contains("unavailable")
    {
        "Not captured"
    } else if explicit.contains("empty") {
        "Empty"
    } else {
        match value {
            None | Some(Value::Null) => "Not captured",
            Some(Value::String(s)) if s.is_empty() => "Empty",
            Some(Value::Array(a)) if a.is_empty() => "Empty",
            Some(Value::Object(o)) if o.is_empty() => "Empty",
            _ => "Produced",
        }
    }
}

fn recorded(value: Option<&Value>) -> Option<&Value> {
    value.filter(|v| capture_state(Some(v), "") == "Produced")
}

fn first_event_value<'a>(events: &'a [Value], keys: &[&str]) -> Option<&'a Value> {
    events.iter().find_map(|event| {
        let payload = event.get("payload").unwrap_or(event);
        keys.iter().find_map(|key| recorded(payload.get(*key)))
    })
}

pub struct Trace<'a> {
    pub session: &'a Value,
    pub events: &'a [Value],
    pub input: Option<&'a Value>,
    pub output: Option<&'a Value>,
}

pub fn trace(value: &Value) -> Option<Trace<'_>> {
    let session = value.get("session")?;
    let events = value
        .get("events")
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .unwrap_or(&[]);
    let input = first_event_value(
        events,
        &["prompt", "messages", "input", "arguments", "query"],
    )
    .or_else(|| recorded(session.get("effective_payload")))
    .or_else(|| recorded(session.get("request")))
    .or_else(|| first_event_value(events, &["request", "request_body", "payload"]));
    let output = recorded(session.get("output"))
        .or_else(|| recorded(session.pointer("/response/text")))
        .or_else(|| recorded(session.pointer("/response/message/content")))
        .or_else(|| recorded(session.get("response")))
        .or_else(|| {
            first_event_value(
                events,
                &[
                    "output",
                    "output_text",
                    "generated_text",
                    "result",
                    "response",
                ],
            )
        });
    Some(Trace {
        session,
        events,
        input,
        output,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn redacts_nested_credentials_without_mutating_raw() {
        let raw = json!({"nested":{"apiKey":"secret-value","Cookie":"a=b","prompt":"review code","private_key":"secret"},"count":0});
        let safe = sanitize(&raw);
        assert_eq!(safe["nested"]["apiKey"], "[redacted]");
        assert_eq!(safe["nested"]["Cookie"], "[redacted]");
        assert_eq!(safe["nested"]["private_key"], "[redacted]");
        assert_eq!(safe["nested"]["prompt"], "review code");
        assert_eq!(safe["count"], 0);
        assert_eq!(raw["nested"]["apiKey"], "secret-value");
    }
    #[test]
    fn capture_states_distinguish_empty_missing_redacted_and_false() {
        assert_eq!(capture_state(None, ""), "Not captured");
        assert_eq!(capture_state(Some(&json!([])), ""), "Empty");
        assert_eq!(capture_state(Some(&json!(false)), ""), "Produced");
        assert_eq!(capture_state(Some(&json!("<redacted>")), ""), "Redacted");
    }
    #[test]
    fn primary_model_input_and_output_keep_structured_payloads() {
        let raw = json!({"session":{"request":{"wrapper":true},"output":{"findings":[{"severity":"high"}]}},
            "events":[{"event_type":"model_request","payload":{"prompt":"review"}}]});
        let projection = trace(&raw).unwrap();
        assert_eq!(projection.input, Some(&json!("review")));
        assert_eq!(
            projection.output.unwrap()["findings"][0]["severity"],
            "high"
        );
        assert_eq!(projection.events.len(), 1);
    }
    #[test]
    fn embedded_credential_headers_are_not_primary_text() {
        assert!(!sanitize(&json!("Authorization: Bearer example-secret"))
            .to_string()
            .contains("example-secret"));
    }
}
