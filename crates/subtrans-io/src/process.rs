use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Duration;

use anyhow::{Context, Result, bail};

pub fn run_capture(
    program: &str,
    args: &[String],
    timeout: Duration,
    scratch: &Path,
) -> Result<Vec<u8>> {
    ensure_executable(program)?;
    let stdout_path = scratch.join(format!(
        "stdout-{}",
        sha256_bytes(args.join("\0").as_bytes())
    ));
    let stderr_path = scratch.join(format!(
        "stderr-{}",
        sha256_bytes(args.join("\0").as_bytes())
    ));
    let stdout = std::fs::File::create(&stdout_path)?;
    let stderr = std::fs::File::create(&stderr_path)?;
    let mut child = Command::new(program)
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .spawn()
        .with_context(|| {
            format!(
                "failed to launch {program}. {}",
                executable_install_guidance(program)
            )
        })?;
    let deadline = std::time::Instant::now() + timeout;
    let status = loop {
        if let Some(status) = child.try_wait()? {
            break status;
        }
        if std::time::Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            bail!(
                "external process {program} exceeded {} seconds",
                timeout.as_secs()
            );
        }
        std::thread::sleep(Duration::from_millis(100));
    };
    let stderr = read_limited(&stderr_path, 64 * 1024)?;
    if !status.success() {
        let stderr = String::from_utf8_lossy(&stderr);
        bail!(
            "external process {program} failed with {status}: {stderr}\n{}",
            process_failure_guidance(program, &stderr)
        );
    }
    read_limited(&stdout_path, 16 * 1024 * 1024)
}

pub fn ensure_executable(command: &str) -> Result<PathBuf> {
    let candidate = Path::new(command);
    if candidate.components().count() > 1 {
        if candidate.is_file() {
            return Ok(candidate.to_owned());
        }
        bail!(
            "configured executable {} does not exist. {}",
            candidate.display(),
            executable_install_guidance(command)
        );
    }
    let path = std::env::var_os("PATH").with_context(|| {
        format!(
            "PATH is not set, so {command} cannot be located. {}",
            executable_install_guidance(command)
        )
    })?;
    std::env::split_paths(&path)
        .map(|directory| directory.join(command))
        .find(|candidate| candidate.is_file())
        .with_context(|| {
            format!(
                "{command} was not found on PATH. {}",
                executable_install_guidance(command)
            )
        })
}

pub fn executable_install_guidance(command: &str) -> String {
    let name = Path::new(command)
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or(command)
        .to_ascii_lowercase();
    match name.as_str() {
        "ffmpeg" | "ffprobe" => format!(
            "On macOS install both tools with `brew install ffmpeg`, verify `{name} -version`, or set [subtitles].{name} to an executable absolute path; then run `subtrans doctor --config <CONFIG>`."
        ),
        "python" | "python3" => "Install Python with `brew install python`, create/activate the worker virtual environment, install the module named in the error with `python3 -m pip install <PACKAGE>`, and configure the worker command as that environment's absolute Python path.".into(),
        _ => format!(
            "Install the required component, verify `{command} --version`, ensure it is executable and on PATH, or configure its absolute path. For ASR/PGS workers also set enabled=true, args with {{input}}/{{output}}, version_args, and a matching stable version; then run `subtrans doctor --config <CONFIG>`."
        ),
    }
}

pub fn process_failure_guidance(program: &str, stderr: &str) -> String {
    if stderr.contains("ModuleNotFoundError") || stderr.contains("No module named") {
        return "A Python module is missing. Activate the exact virtual environment used by the configured worker, install the module named above with `python3 -m pip install <PACKAGE>`, verify the worker's version command, and rerun `subtrans doctor --config <CONFIG>`. subtrans will not install modules automatically.".into();
    }
    executable_install_guidance(program)
}

fn read_limited(path: &Path, limit: usize) -> Result<Vec<u8>> {
    let metadata = std::fs::metadata(path)?;
    if metadata.len() > limit as u64 {
        bail!("external process output exceeded {limit} bytes");
    }
    Ok(std::fs::read(path)?)
}

fn sha256_bytes(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    hex::encode(Sha256::digest(bytes))
}

#[cfg(test)]
mod tests {
    use super::{ensure_executable, executable_install_guidance, run_capture};
    use std::time::Duration;

    #[test]
    fn external_process_timeout_is_enforced() {
        let scratch = tempfile::tempdir().unwrap();
        let error = run_capture(
            "/bin/sleep",
            &["2".to_owned()],
            Duration::from_millis(10),
            scratch.path(),
        )
        .unwrap_err();
        assert!(error.to_string().contains("exceeded"));
    }

    #[test]
    fn missing_ffmpeg_error_contains_install_and_verification_steps() {
        let error = ensure_executable("ffmpeg-subtrans-definitely-missing").unwrap_err();
        let message = format!("{error:#}");
        assert!(message.contains("was not found on PATH"));
        assert!(message.contains("Install the required component"));
        assert!(message.contains("subtrans doctor"));

        let guidance = executable_install_guidance("ffmpeg");
        assert!(guidance.contains("brew install ffmpeg"));
        assert!(guidance.contains("ffmpeg -version"));
    }

    #[test]
    fn missing_python_module_error_contains_manual_pip_guidance() {
        let scratch = tempfile::tempdir().unwrap();
        let error = run_capture(
            "/bin/sh",
            &[
                "-c".into(),
                "echo \"ModuleNotFoundError: No module named 'whisper'\" >&2; exit 1".into(),
            ],
            Duration::from_secs(5),
            scratch.path(),
        )
        .unwrap_err();
        let message = format!("{error:#}");
        assert!(message.contains("No module named 'whisper'"));
        assert!(message.contains("python3 -m pip install"));
        assert!(message.contains("will not install modules automatically"));
    }
}
