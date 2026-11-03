mod support;

use std::fs;
use std::sync::Mutex;

use anyhow::{Result, bail};
use subtrans::artifact::read_ready_artifact;
use subtrans::remote::{LlmClient, LlmCompletion, LlmProbe};
use subtrans::state::StateStore;
use subtrans::storage::{LocalStorage, Storage};
use subtrans::subtitles::{SubtitleCheckpoint, SubtitleStage, run_with_stage};
use tempfile::tempdir;

struct RecordingLlm {
    replies: Mutex<Vec<String>>,
    prompts: Mutex<Vec<String>>,
    reject_containing: Mutex<Vec<String>>,
}

impl RecordingLlm {
    fn new(replies: Vec<String>) -> Self {
        Self {
            replies: Mutex::new(replies),
            prompts: Mutex::new(Vec::new()),
            reject_containing: Mutex::new(Vec::new()),
        }
    }

    fn reject_if_prompt_contains(&self, needle: &str) {
        self.reject_containing
            .lock()
            .expect("reject lock")
            .push(needle.to_owned());
    }

    fn prompts(&self) -> Vec<String> {
        self.prompts.lock().expect("prompt lock").clone()
    }
}

impl LlmClient for RecordingLlm {
    fn complete(&self, request: &LlmCompletion<'_>) -> Result<String> {
        self.prompts
            .lock()
            .expect("prompt lock")
            .push(request.prompt.to_owned());
        for needle in self.reject_containing.lock().expect("reject lock").iter() {
            if request.prompt.contains(needle) {
                bail!("refusing to repeat settled work containing {needle}");
            }
        }
        self.replies
            .lock()
            .expect("reply lock")
            .pop()
            .context_missing()
    }

    fn probe(&self, _request: &LlmProbe<'_>) -> Result<String> {
        Ok(r#"{"models":[]}"#.to_owned())
    }
}

trait MissingReply {
    fn context_missing(self) -> Result<String>;
}

impl MissingReply for Option<String> {
    fn context_missing(self) -> Result<String> {
        self.ok_or_else(|| anyhow::anyhow!("scripted LLM has no remaining replies"))
    }
}

fn lay_video(source: &std::path::Path) {
    fs::create_dir_all(source).unwrap();
    fs::write(source.join("Stage.Movie.2026.WEB-DL.mkv"), b"video").unwrap();
    let srt = "1\n00:00:01,000 --> 00:00:02,000\nALPHA CUE\n\n2\n00:00:03,000 --> 00:00:04,000\nBETA CUE\n\n";
    fs::write(source.join("Stage.Movie.2026.WEB-DL.en.srt"), srt).unwrap();
    fs::write(source.join("Stage.Movie.2026.WEB-DL.emb.srt"), srt).unwrap();
}

fn stage_config(
    root: &std::path::Path,
    source: &std::path::Path,
    destination: &std::path::Path,
) -> subtrans::config::Config {
    let mut cfg = support::config(root, source, destination);
    cfg.translation.batch_size = 1;
    cfg.translation.context_cues = 0;
    cfg.translation.max_retries = 0;
    cfg.translation.alignment_batch_size = 1;
    cfg.translation.alignment_context_cues = 0;
    cfg.translation.consistency_check = false;
    cfg.translation.alignment_check = true;
    cfg.translation.alignment_model = Some("review-model".into());
    cfg
}

fn translation_reply(index: u32, text: &str) -> String {
    serde_json::json!({"translations":[{"index": index, "text": text}]}).to_string()
}

fn review_reply(index: u32, text: &str) -> String {
    serde_json::json!({"corrections":[{"index": index, "text": text}]}).to_string()
}

fn checkpoints(database: &std::path::Path) -> Vec<(String, SubtitleCheckpoint)> {
    let store = StateStore::open(database).unwrap();
    store
        .subtitle_checkpoints()
        .unwrap()
        .into_iter()
        .map(|(job_id, payload)| {
            (
                job_id,
                serde_json::from_str(&payload).expect("checkpoint json"),
            )
        })
        .collect()
}

fn ready_exists(source: &std::path::Path) -> bool {
    let storage = LocalStorage::new(source).unwrap();
    let entry = storage
        .metadata("Stage.Movie.2026.WEB-DL.mkv")
        .unwrap()
        .unwrap();
    read_ready_artifact(&storage, &entry).unwrap().is_some()
}

#[test]
fn translate_stage_does_not_call_review_or_publish() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&destination).unwrap();
    lay_video(&source);
    let cfg = stage_config(root.path(), &source, &destination);
    let llm = RecordingLlm::new(vec![
        translation_reply(2, "乙侧译文"),
        translation_reply(1, "甲侧译文"),
    ]);

    run_with_stage(
        &cfg,
        false,
        false,
        None,
        SubtitleStage::Translate,
        Some(&llm),
        None,
    )
    .unwrap();

    assert!(
        llm.prompts()
            .iter()
            .all(|prompt| !prompt.contains("final subtitle reviewer")),
        "translate stage called the review model: {:?}",
        llm.prompts()
    );
    assert!(!ready_exists(&source));
    let saved = checkpoints(&cfg.state.database);
    assert_eq!(saved.len(), 1);
    assert!(saved[0].1.settled_indices.contains(&1));
    assert!(saved[0].1.settled_indices.contains(&2));
    assert!(saved[0].1.reviewed_indices.is_empty());
}

#[test]
fn review_stage_publishes_without_translating_again() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&destination).unwrap();
    lay_video(&source);
    let cfg = stage_config(root.path(), &source, &destination);
    let translator = RecordingLlm::new(vec![
        translation_reply(2, "乙侧译文"),
        translation_reply(1, "甲侧译文"),
    ]);
    run_with_stage(
        &cfg,
        false,
        false,
        None,
        SubtitleStage::Translate,
        Some(&translator),
        None,
    )
    .unwrap();

    let reviewer = RecordingLlm::new(vec![
        review_reply(2, "乙侧译文"),
        review_reply(1, "甲侧译文"),
    ]);
    run_with_stage(
        &cfg,
        false,
        false,
        None,
        SubtitleStage::Review,
        Some(&reviewer),
        None,
    )
    .unwrap();

    assert!(
        reviewer
            .prompts()
            .iter()
            .all(|prompt| prompt.contains("final subtitle reviewer")),
        "review stage called translation: {:?}",
        reviewer.prompts()
    );
    assert!(ready_exists(&source));
    assert!(checkpoints(&cfg.state.database).is_empty());
}

#[test]
fn review_without_checkpoint_fails_closed() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&destination).unwrap();
    lay_video(&source);
    let cfg = stage_config(root.path(), &source, &destination);
    let llm = RecordingLlm::new(vec![translation_reply(1, "甲侧译文")]);

    let error = run_with_stage(
        &cfg,
        false,
        false,
        None,
        SubtitleStage::Review,
        Some(&llm),
        None,
    )
    .unwrap_err();

    assert!(
        error.to_string().contains("checkpoint"),
        "unexpected error: {error:#}"
    );
    assert!(llm.prompts().is_empty());
    assert!(!ready_exists(&source));
}

#[test]
fn translation_resumes_without_repeating_settled_cues() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&destination).unwrap();
    lay_video(&source);
    let cfg = stage_config(root.path(), &source, &destination);
    let first = RecordingLlm::new(vec![
        translation_reply(2, "乙侧译文"),
        translation_reply(1, "甲侧译文"),
    ]);
    run_with_stage(
        &cfg,
        false,
        false,
        None,
        SubtitleStage::Translate,
        Some(&first),
        None,
    )
    .unwrap();

    let saved = checkpoints(&cfg.state.database);
    let (job_id, mut document) = saved.into_iter().next().unwrap();
    document.settled_indices.remove(&2);
    document.translations.remove(&2);
    let mut store = StateStore::open(&cfg.state.database).unwrap();
    store
        .save_subtitle_checkpoint(&job_id, &serde_json::to_string(&document).unwrap())
        .unwrap();
    drop(store);

    let second = RecordingLlm::new(vec![translation_reply(2, "乙侧译文")]);
    second.reject_if_prompt_contains("ALPHA CUE");
    run_with_stage(
        &cfg,
        false,
        false,
        None,
        SubtitleStage::Translate,
        Some(&second),
        None,
    )
    .unwrap();

    assert_eq!(second.prompts().len(), 1);
    assert!(second.prompts()[0].contains("BETA CUE"));
    let saved = checkpoints(&cfg.state.database);
    assert!(saved[0].1.settled_indices.contains(&1));
    assert!(saved[0].1.settled_indices.contains(&2));
}

#[test]
fn review_resumes_without_repeating_reviewed_cues() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&destination).unwrap();
    lay_video(&source);
    let cfg = stage_config(root.path(), &source, &destination);
    let translator = RecordingLlm::new(vec![
        translation_reply(2, "乙侧译文"),
        translation_reply(1, "甲侧译文"),
    ]);
    run_with_stage(
        &cfg,
        false,
        false,
        None,
        SubtitleStage::Translate,
        Some(&translator),
        None,
    )
    .unwrap();

    let saved = checkpoints(&cfg.state.database);
    let (job_id, mut document) = saved.into_iter().next().unwrap();
    document.reviewed_indices.insert(1);
    let mut store = StateStore::open(&cfg.state.database).unwrap();
    store
        .save_subtitle_checkpoint(&job_id, &serde_json::to_string(&document).unwrap())
        .unwrap();
    drop(store);

    let reviewer = RecordingLlm::new(vec![review_reply(2, "乙侧译文")]);
    reviewer.reject_if_prompt_contains("ALPHA CUE");
    run_with_stage(
        &cfg,
        false,
        false,
        None,
        SubtitleStage::Review,
        Some(&reviewer),
        None,
    )
    .unwrap();

    assert_eq!(reviewer.prompts().len(), 1);
    assert!(reviewer.prompts()[0].contains("BETA CUE"));
    assert!(ready_exists(&source));
}

#[test]
fn checkpoint_does_not_store_the_api_key() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&destination).unwrap();
    lay_video(&source);
    let mut cfg = stage_config(root.path(), &source, &destination);
    cfg.translation.api_key_env = Some("SUBTRANS_STAGE_TEST_TOKEN".into());
    let secret = "stage-token-should-not-persist";
    unsafe { std::env::set_var("SUBTRANS_STAGE_TEST_TOKEN", secret) };
    let llm = RecordingLlm::new(vec![
        translation_reply(2, "乙侧译文"),
        translation_reply(1, "甲侧译文"),
    ]);

    run_with_stage(
        &cfg,
        false,
        false,
        None,
        SubtitleStage::Translate,
        Some(&llm),
        None,
    )
    .unwrap();

    let store = StateStore::open(&cfg.state.database).unwrap();
    let payload = store
        .subtitle_checkpoints()
        .unwrap()
        .into_iter()
        .map(|(_, payload)| payload)
        .collect::<Vec<_>>()
        .join("\n");
    assert!(!payload.contains(secret));
    assert!(payload.contains("甲侧译文"));
}
