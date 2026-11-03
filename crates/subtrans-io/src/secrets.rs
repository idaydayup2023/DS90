use anyhow::{Context, Result, bail};

pub fn resolve_ftp_username(environment_name: &str) -> Result<String> {
    let username = std::env::var(environment_name)
        .with_context(|| format!("missing FTP username environment variable {environment_name}"))?;
    if username.trim().is_empty() {
        bail!("FTP username environment variable {environment_name} is empty");
    }
    Ok(username)
}

pub fn tmdb_token_setup_guidance(environment_name: &str) -> String {
    let mut guidance = format!(
        "Get an API Read Access Token at https://www.themoviedb.org/settings/api, then set it for this shell with `read -s \"{environment_name}?TMDB read token: \"; export {environment_name}; echo`"
    );
    if cfg!(target_os = "macos") {
        guidance.push_str(
            &format!(
                "; to make it available to current-user launchd jobs without exposing it in shell history, run `read -s \"{environment_name}?TMDB read token: \"; launchctl setenv {environment_name} \"${environment_name}\"; export {environment_name}; echo`; for restart-safe fallback reuse that environment value with `security add-generic-password -U -a \"$USER\" -s \"subtrans.tmdb.read-token\" -w \"${environment_name}\"`"
            ),
        );
    }
    guidance.push_str("; verify with `subtrans doctor --config subtrans.toml`");
    guidance
}

pub fn read_tmdb_read_token(environment_name: &str) -> Result<String> {
    match std::env::var(environment_name) {
        Ok(token) if !token.trim().is_empty() => return Ok(token),
        Ok(_) => bail!(
            "TMDB API read token environment variable {} is empty. {}",
            environment_name,
            tmdb_token_setup_guidance(environment_name)
        ),
        Err(std::env::VarError::NotUnicode(_)) => bail!(
            "TMDB API read token environment variable {} is not valid Unicode. {}",
            environment_name,
            tmdb_token_setup_guidance(environment_name)
        ),
        Err(std::env::VarError::NotPresent) => {}
    }

    #[cfg(target_os = "macos")]
    {
        let output = std::process::Command::new("/bin/launchctl")
            .args(["getenv", environment_name])
            .output()
            .context(
                "failed to query the current macOS launchd environment for the TMDB API read token",
            )?;
        if output.status.success() {
            let token = String::from_utf8(output.stdout).context(
                "TMDB API read token from the macOS launchd environment is not valid Unicode",
            )?;
            let token = token.trim_end_matches(['\r', '\n']).to_owned();
            if !token.trim().is_empty() {
                return Ok(token);
            }
        }

        let output = std::process::Command::new("/usr/bin/security")
            .args([
                "find-generic-password",
                "-s",
                "subtrans.tmdb.read-token",
                "-w",
            ])
            .output()
            .context("failed to query macOS Keychain for the TMDB API read token")?;
        if output.status.success() {
            let token = String::from_utf8(output.stdout)
                .context("TMDB API read token from macOS Keychain is not valid Unicode")?;
            let token = token.trim_end_matches(['\r', '\n']).to_owned();
            if !token.trim().is_empty() {
                return Ok(token);
            }
        }
    }

    bail!(
        "missing TMDB API read token. {}",
        tmdb_token_setup_guidance(environment_name)
    )
}
