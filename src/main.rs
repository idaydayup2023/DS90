use std::path::PathBuf;

use anyhow::Result;
use clap::{Parser, Subcommand};
use subtrans::config::Config;

#[derive(Debug, Parser)]
#[command(
    name = "subtrans",
    version,
    about = "TMDB metadata, subtitle translation, and safe media migration",
    long_about = "TMDB metadata, subtitle translation, and safe media migration.\n\nThis product uses the TMDB API but is not endorsed or certified by TMDB."
)]
struct Cli {
    /// Print diagnostics as one JSON object per line on stdout.
    #[arg(long, global = true)]
    json: bool,
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    /// Fetch TMDB artwork and metadata before translation or migration.
    Metadata {
        #[arg(long)]
        config: PathBuf,
        /// Process this local directory recursively instead of configured source storage.
        #[arg(long, value_name = "DIRECTORY")]
        local_dir: Option<PathBuf>,
        /// Keep existing local artwork and fill only missing files.
        #[arg(long, conflicts_with = "force")]
        supplement: bool,
        /// Refresh and replace all subtrans-managed or existing metadata files.
        #[arg(long)]
        force: bool,
        #[arg(long)]
        dry_run: bool,
        #[arg(long)]
        limit: Option<usize>,
    },
    /// Scan media, acquire source subtitles, translate, validate, and publish.
    Subtitles {
        #[arg(long)]
        config: PathBuf,
        /// Translate media in this local directory instead of configured source storage.
        #[arg(long, value_name = "DIRECTORY")]
        local_dir: Option<PathBuf>,
        #[arg(long)]
        dry_run: bool,
        #[arg(long)]
        force: bool,
        #[arg(long)]
        limit: Option<usize>,
        /// Run translation, review, or both. Review publishes; translation only checkpoints.
        #[arg(long, value_enum, default_value_t = SubtitleStageArg::Both)]
        stage: SubtitleStageArg,
    },
    /// Build or apply auditable media migration plans.
    Migrate {
        #[command(subcommand)]
        command: MigrateCommand,
    },
    /// Validate configuration and required external services.
    Doctor {
        #[arg(long)]
        config: PathBuf,
    },
}

#[derive(Debug, Clone, Copy, clap::ValueEnum)]
enum SubtitleStageArg {
    Translate,
    Review,
    Both,
}

impl From<SubtitleStageArg> for subtrans::subtitles::SubtitleStage {
    fn from(stage: SubtitleStageArg) -> Self {
        match stage {
            SubtitleStageArg::Translate => subtrans::subtitles::SubtitleStage::Translate,
            SubtitleStageArg::Review => subtrans::subtitles::SubtitleStage::Review,
            SubtitleStageArg::Both => subtrans::subtitles::SubtitleStage::Both,
        }
    }
}

#[derive(Debug, Subcommand)]
enum MigrateCommand {
    Plan {
        #[arg(long)]
        config: PathBuf,
        #[arg(long)]
        output: PathBuf,
        #[arg(long)]
        limit: Option<usize>,
    },
    Apply {
        #[arg(long)]
        config: PathBuf,
        #[arg(long)]
        plan: PathBuf,
        #[arg(long)]
        approve: String,
        /// Apply only ready items and leave audited pending sources untouched.
        #[arg(long)]
        allow_pending: bool,
    },
    /// Explain every pending decision and show the exact override key to edit.
    Review {
        #[arg(long)]
        config: PathBuf,
        #[arg(long)]
        plan: PathBuf,
    },
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    subtrans_core::report::set_json(cli.json);
    match cli.command {
        Command::Metadata {
            config,
            local_dir,
            supplement,
            force,
            dry_run,
            limit,
        } => {
            let mut cfg = load_runtime_config(config)?;
            if let Some(local_dir) = local_dir {
                cfg.source = subtrans::config::StorageConfig::Local {
                    root: local_dir.clone(),
                };
                subtrans_core::report_line!(
                    out,
                    "metadata.local_mode",
                    serde_json::json!({"root": local_dir.display().to_string()}),
                    "metadata local_mode root={}",
                    local_dir.display()
                );
            }
            let mode = if force {
                subtrans::metadata::FetchMode::Force
            } else if supplement {
                subtrans::metadata::FetchMode::Supplement
            } else {
                subtrans::metadata::FetchMode::Default
            };
            subtrans::metadata::run(&cfg, mode, dry_run, limit).map(|_| ())
        }
        Command::Subtitles {
            config,
            local_dir,
            dry_run,
            force,
            limit,
            stage,
        } => {
            let mut cfg = load_runtime_config(config)?;
            if let Some(local_dir) = local_dir {
                cfg.source = subtrans::config::StorageConfig::Local {
                    root: local_dir.clone(),
                };
                subtrans_core::report_line!(
                    out,
                    "subtitle.local_mode",
                    serde_json::json!({
                        "root": local_dir.display().to_string(),
                        "migration": "disabled"
                    }),
                    "subtitles local_mode root={} migration=disabled",
                    local_dir.display()
                );
            }
            subtrans::subtitles::run_with_stage(
                &cfg,
                dry_run,
                force,
                limit,
                stage.into(),
                None,
                None,
            )
        }
        Command::Migrate { command } => match command {
            MigrateCommand::Plan {
                config,
                output,
                limit,
            } => {
                let cfg = load_runtime_config(config)?;
                let plan = subtrans::migration::build_plan(&cfg, limit)?;
                plan.write(&output)?;
                subtrans_core::report_line!(
                    out,
                    "plan.ready",
                    serde_json::json!({
                        "plan_hash": plan.plan_hash,
                        "items": plan.items.len(),
                        "pending": plan.pending_count()
                    }),
                    "plan_hash={} items={} pending={}",
                    plan.plan_hash,
                    plan.items.len(),
                    plan.pending_count()
                );
                Ok(())
            }
            MigrateCommand::Apply {
                config,
                plan,
                approve,
                allow_pending,
            } => {
                let cfg = load_runtime_config(config)?;
                let plan = subtrans::migration::PlanDocument::read(&plan)?;
                if allow_pending {
                    subtrans::migration::apply_plan_allow_pending(&cfg, &plan, &approve)
                } else {
                    subtrans::migration::apply_plan(&cfg, &plan, &approve)
                }
            }
            MigrateCommand::Review { config, plan } => {
                let cfg = load_runtime_config(config)?;
                let plan = subtrans::migration::PlanDocument::read(&plan)?;
                plan.verify_config(&cfg)?;
                if plan.pending_count() == 0 {
                    subtrans_core::report_line!(
                        out,
                        "migrate.review",
                        serde_json::json!({"pending": 0, "plan_hash": plan.plan_hash}),
                        "No pending items. Apply only with plan_hash={}",
                        plan.plan_hash
                    );
                    return Ok(());
                }
                for item in plan.items.iter().filter(|item| item.is_pending()) {
                    let reason = match &item.status {
                        subtrans::migration::PlanStatus::Pending { reason } => reason.clone(),
                        subtrans::migration::PlanStatus::Ready => String::new(),
                    };
                    let override_key = format!(
                        "[migration.overrides.{}]",
                        serde_json::to_string(&item.source)?
                    );
                    let mut lines = vec![format!("PENDING {}", item.source)];
                    if let subtrans::migration::PlanStatus::Pending { reason } = &item.status {
                        lines.push(format!("  reason: {reason}"));
                    }
                    if let Some(destination) = &item.proposed_destination {
                        lines.push(format!(
                            "  proposed destination (not executable): {destination}"
                        ));
                    }
                    for evidence in &item.classification.evidence {
                        lines.push(format!(
                            "  evidence: {} ({:.2}) {}",
                            evidence.code, evidence.confidence, evidence.detail
                        ));
                    }
                    lines.push(format!("  override key: {override_key}"));
                    let mut fields = serde_json::json!({
                        "source": item.source,
                        "reason": reason,
                        "override_key": override_key,
                        "evidence": item.classification.evidence.iter().map(|evidence| {
                            serde_json::json!({
                                "code": evidence.code,
                                "confidence": format!("{:.2}", evidence.confidence),
                                "detail": evidence.detail
                            })
                        }).collect::<Vec<_>>()
                    });
                    if let Some(destination) = &item.proposed_destination {
                        fields["proposed_destination"] = serde_json::json!(destination);
                    }
                    subtrans_core::report::emit_lines(
                        subtrans_core::report::Stream::Stdout,
                        &lines,
                        "migrate.pending",
                        fields,
                    );
                }
                subtrans_core::report_line!(
                    out,
                    "migrate.hint",
                    serde_json::json!({
                        "message": "Edit explicit overrides in the TOML config, then generate and review a new plan. Never edit this plan file."
                    }),
                    "Edit explicit overrides in the TOML config, then generate and review a new plan. Never edit this plan file."
                );
                Ok(())
            }
        },
        Command::Doctor { config } => {
            let cfg = load_runtime_config(config)?;
            subtrans::storage::doctor(&cfg.source)?;
            subtrans::storage::doctor(&cfg.destination)?;
            subtrans::storage::doctor_writable(&cfg.source, "", "source storage root")?;
            for (name, root) in [
                ("movie_4k", &cfg.migration.layouts.movie_4k.root),
                ("movie_other", &cfg.migration.layouts.movie_other.root),
                ("tv_4k", &cfg.migration.layouts.tv_4k.root),
                ("tv_other", &cfg.migration.layouts.tv_other.root),
            ] {
                subtrans::storage::doctor_writable(
                    &cfg.destination,
                    root,
                    &format!("migration.layouts.{name}.root"),
                )?;
            }
            subtrans::subtitles::doctor(&cfg)?;
            subtrans::metadata::doctor(&cfg)?;
            subtrans_core::report_line!(
                out,
                "doctor.ready",
                serde_json::json!({"version": subtrans::VERSION}),
                "subtrans {} configuration and dependencies are ready",
                subtrans::VERSION
            );
            Ok(())
        }
    }
}

fn load_runtime_config(path: PathBuf) -> Result<Config> {
    Config::load(path)
}
