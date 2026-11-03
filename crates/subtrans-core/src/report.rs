//! Diagnostic channel for human sentences and `--json` events.
//!
//! The default rendering is the existing sentence on stdout or stderr.
//! JSON mode writes one object per diagnostic to stdout. An empty human
//! sentence emits an event only in JSON mode, so a new event does not add
//! a human line.

use std::cell::RefCell;

use serde_json::{Map, Value};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Stream {
    Stdout,
    Stderr,
}

struct State {
    json: bool,
    capture: Option<Vec<(Stream, String)>>,
}

thread_local! {
    static STATE: RefCell<State> = const {
        RefCell::new(State {
            json: false,
            capture: None,
        })
    };
}

pub fn set_json(enabled: bool) {
    STATE.with(|state| state.borrow_mut().json = enabled);
}

pub struct CaptureGuard {
    previous_json: bool,
}

impl Drop for CaptureGuard {
    fn drop(&mut self) {
        STATE.with(|state| {
            let mut state = state.borrow_mut();
            state.json = self.previous_json;
            state.capture = None;
        });
    }
}

/// Record emitted lines on this thread instead of writing to the terminal.
pub fn capture(json: bool) -> CaptureGuard {
    STATE.with(|state| {
        let mut state = state.borrow_mut();
        let previous_json = state.json;
        state.json = json;
        state.capture = Some(Vec::new());
        CaptureGuard { previous_json }
    })
}

pub fn captured() -> Vec<(Stream, String)> {
    STATE.with(|state| state.borrow().capture.clone().unwrap_or_default())
}

pub fn emit(stream: Stream, human: &str, event: &str, fields: Value) {
    if human.is_empty() {
        emit_lines(stream, &[], event, fields);
    } else {
        emit_lines(stream, &[human.to_owned()], event, fields);
    }
}

/// Several human lines that describe one fact become one JSON event.
pub fn emit_lines(stream: Stream, human_lines: &[String], event: &str, fields: Value) {
    let json = STATE.with(|state| state.borrow().json);
    if json {
        publish(Stream::Stdout, &render_json(event, &fields), true);
        return;
    }
    for line in human_lines {
        if !line.is_empty() {
            publish(stream, line, false);
        }
    }
}

pub fn render_json(event: &str, fields: &Value) -> String {
    let mut object = Map::new();
    object.insert("event".to_owned(), Value::String(event.to_owned()));
    if let Value::Object(map) = fields {
        for (key, value) in map {
            if key != "event" {
                object.insert(key.clone(), value.clone());
            }
        }
    }
    serde_json::to_string(&Value::Object(object)).expect("diagnostic event is valid JSON")
}

fn publish(stream: Stream, line: &str, json_mode: bool) {
    let captured = STATE.with(|state| {
        let mut state = state.borrow_mut();
        if let Some(buffer) = state.capture.as_mut() {
            let recorded = if json_mode { Stream::Stdout } else { stream };
            buffer.push((recorded, line.to_owned()));
            true
        } else {
            false
        }
    });
    if captured {
        return;
    }
    if json_mode || matches!(stream, Stream::Stdout) {
        println!("{line}");
    } else {
        eprintln!("{line}");
    }
}

#[macro_export]
macro_rules! report_line {
    (out, $event:expr, $fields:expr, $($arg:tt)*) => {{
        $crate::report::emit(
            $crate::report::Stream::Stdout,
            &format!($($arg)*),
            $event,
            $fields,
        );
    }};
    (err, $event:expr, $fields:expr, $($arg:tt)*) => {{
        $crate::report::emit(
            $crate::report::Stream::Stderr,
            &format!($($arg)*),
            $event,
            $fields,
        );
    }};
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn human_mode_records_the_sentence_on_its_stream() {
        let _guard = capture(false);
        emit(
            Stream::Stderr,
            "scan empty_dir path=incoming/show",
            "scan.empty_dir",
            json!({"path": "incoming/show"}),
        );
        assert_eq!(
            captured(),
            vec![(
                Stream::Stderr,
                "scan empty_dir path=incoming/show".to_owned()
            )]
        );
    }

    #[test]
    fn json_mode_emits_one_object_and_keeps_the_event_name() {
        let _guard = capture(true);
        emit(
            Stream::Stderr,
            "ignored human sentence",
            "scan.empty_dir",
            json!({"event": "replaced", "path": "incoming/show"}),
        );
        let lines = captured();
        assert_eq!(lines.len(), 1);
        assert_eq!(lines[0].0, Stream::Stdout);
        let value: Value = serde_json::from_str(&lines[0].1).unwrap();
        assert_eq!(value["event"], "scan.empty_dir");
        assert_eq!(value["path"], "incoming/show");
        assert!(!lines[0].1.contains("ignored human sentence"));
    }

    #[test]
    fn empty_human_text_is_silent_until_json_mode() {
        let _human = capture(false);
        emit(Stream::Stdout, "", "subtitle.blocked", json!({"index": 12}));
        assert!(captured().is_empty());
        drop(_human);
        let _json = capture(true);
        emit(
            Stream::Stdout,
            "",
            "subtitle.blocked",
            json!({"video": "a.mkv", "reason": "review_failed", "index": 12}),
        );
        let value: Value = serde_json::from_str(&captured()[0].1).unwrap();
        assert_eq!(value["event"], "subtitle.blocked");
        assert_eq!(value["video"], "a.mkv");
        assert_eq!(value["reason"], "review_failed");
        assert_eq!(value["index"], 12);
    }

    #[test]
    fn several_human_lines_collapse_to_one_event() {
        let _guard = capture(true);
        emit_lines(
            Stream::Stdout,
            &["PENDING a.mkv".to_owned(), "  reason: unknown".to_owned()],
            "migrate.pending",
            json!({
                "source": "a.mkv",
                "reason": "unknown",
                "override_key": "[migration.overrides.\"a.mkv\"]"
            }),
        );
        assert_eq!(captured().len(), 1);
        let value: Value = serde_json::from_str(&captured()[0].1).unwrap();
        assert_eq!(value["event"], "migrate.pending");
        assert_eq!(value["override_key"], "[migration.overrides.\"a.mkv\"]");
    }

    #[test]
    fn required_events_keep_numeric_fields() {
        let _guard = capture(true);
        emit(
            Stream::Stdout,
            "plan_hash=abc items=10 pending=2",
            "plan.ready",
            json!({"plan_hash": "abc", "items": 10, "pending": 2}),
        );
        let value: Value = serde_json::from_str(&captured()[0].1).unwrap();
        assert_eq!(value["event"], "plan.ready");
        assert_eq!(value["plan_hash"], "abc");
        assert_eq!(value["items"], 10);
        assert_eq!(value["pending"], 2);
    }
}
