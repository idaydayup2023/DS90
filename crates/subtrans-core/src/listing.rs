/// Bracketed FTP paths must be listed from inside the directory.
///
/// An `MLSD` argument that contains `[` or `]` can succeed with an empty
/// listing for a directory that still has entries. Callers cannot tell that
/// from a genuinely empty directory. Paths containing either bracket are
/// listed with `CWD` plus `MLSD` without a path argument.
pub fn needs_directory_listing(remote: &str) -> bool {
    remote.contains('[') || remote.contains(']')
}

#[cfg(test)]
mod tests {
    use super::needs_directory_listing;

    #[test]
    fn bracketed_paths_are_listed_from_inside_the_directory() {
        assert!(needs_directory_listing("/volume1/媒体/[TV] Show/Season 01"));
        assert!(needs_directory_listing("/media/Show [2024]/S01E01"));
        assert!(needs_directory_listing("/media/partial]name"));
    }

    #[test]
    fn plain_paths_keep_the_mlsd_argument_path() {
        assert!(!needs_directory_listing("/"));
        assert!(!needs_directory_listing("/volume1/媒体/Show/Season 01"));
        assert!(!needs_directory_listing("/media/Movie (2024)"));
    }
}
