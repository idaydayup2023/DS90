use anyhow::{Result, bail};

/// Validate and normalize a path at the trust boundary.
///
/// Empty string and `.` mean the storage root. All other paths must use POSIX
/// separators and may not contain empty, dot, parent, NUL, or absolute
/// components.
pub fn validate_relative_path(relative: &str) -> Result<String> {
    if relative.is_empty() || relative == "." {
        return Ok(String::new());
    }
    if relative.starts_with('/') {
        bail!("storage path must be relative: {relative:?}");
    }
    if relative.contains('\0') || relative.contains('\\') {
        bail!("storage path contains an invalid separator or NUL: {relative:?}");
    }

    let mut normalized = Vec::new();
    for component in relative.split('/') {
        if component.is_empty() || component == "." || component == ".." {
            bail!("storage path contains an unsafe component: {relative:?}");
        }
        normalized.push(component);
    }
    Ok(normalized.join("/"))
}
