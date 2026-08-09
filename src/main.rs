use std::path::PathBuf;

use anyhow::Result;
use clap::{Parser, Subcommand};
use subtrans::config::Config;

#[derive(Debug, Parser)]
#[command(
    name = "subtrans",
    version,
    about = "Subtitle translation and safe media migration"
)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    /// Scan media, acquire source subtitles, translate, validate, and publish.
    Subtitles {
        #[arg(long)]
        config: PathBuf,
        #[arg(long)]
        dry_run: bool,
        #[arg(long)]
        force: bool,
        #[arg(long)]
        limit: Option<usize>,
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
    match cli.command {
        Command::Subtitles {
            config,
            dry_run,
            force,
            limit,
        } => {
            let cfg = Config::load(config)?;
            subtrans::subtitles::run(&cfg, dry_run, force, limit)
        }
        Command::Migrate { command } => match command {
            MigrateCommand::Plan {
                config,
                output,
                limit,
            } => {
                let cfg = Config::load(config)?;
                let plan = subtrans::migration::build_plan(&cfg, limit)?;
                plan.write(&output)?;
                println!(
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
            } => {
                let cfg = Config::load(config)?;
                let plan = subtrans::migration::PlanDocument::read(&plan)?;
                subtrans::migration::apply_plan(&cfg, &plan, &approve)
            }
            MigrateCommand::Review { config, plan } => {
                let cfg = Config::load(config)?;
                let plan = subtrans::migration::PlanDocument::read(&plan)?;
                plan.verify_config(&cfg)?;
                if plan.pending_count() == 0 {
                    println!(
                        "No pending items. Apply only with plan_hash={}",
                        plan.plan_hash
                    );
                    return Ok(());
                }
                for item in plan.items.iter().filter(|item| item.is_pending()) {
                    println!("PENDING {}", item.source);
                    if let subtrans::migration::PlanStatus::Pending { reason } = &item.status {
                        println!("  reason: {reason}");
                    }
                    for evidence in &item.classification.evidence {
                        println!(
                            "  evidence: {} ({:.2}) {}",
                            evidence.code, evidence.confidence, evidence.detail
                        );
                    }
                    println!(
                        "  override key: [migration.overrides.{}]",
                        serde_json::to_string(&item.source)?
                    );
                }
                println!(
                    "Edit explicit overrides in the TOML config, then generate and review a new plan. Never edit this plan file."
                );
                Ok(())
            }
        },
        Command::Doctor { config } => {
            let cfg = Config::load(config)?;
            subtrans::storage::doctor(&cfg.source)?;
            subtrans::storage::doctor(&cfg.destination)?;
            subtrans::subtitles::doctor(&cfg)?;
            println!(
                "subtrans {} configuration and dependencies are ready",
                subtrans::VERSION
            );
            Ok(())
        }
    }
}
