mod classifier;
mod executor;
mod planner;

pub use classifier::{Classification, Evidence, MediaKind, RULE_VERSION, classify_path};
pub use executor::{apply_plan, apply_plan_allow_pending};
pub use planner::{FileAction, PlanDocument, PlanItem, PlanStatus, SourceFingerprint, build_plan};
