// Organizer moves regular files into type directories without overwriting files.
package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

var extensions = map[string]string{
	".txt": "documents", ".md": "documents", ".pdf": "documents", ".doc": "documents",
	".docx": "documents", ".odt": "documents", ".csv": "documents", ".xlsx": "documents",
	".jpg": "images", ".jpeg": "images", ".png": "images", ".gif": "images",
	".webp": "images", ".svg": "images", ".bmp": "images",
	".mp4": "videos", ".mkv": "videos", ".mov": "videos", ".avi": "videos", ".webm": "videos",
	".zip": "archives", ".gz": "archives", ".bz2": "archives", ".xz": "archives",
	".tar": "archives", ".7z": "archives", ".rar": "archives",
}

const help = `Organize regular files by type; skip directories, symlinks and unknown extensions.
Usage:
  organizer organize --source DIR [--dry-run]
  organizer categories
  organizer --help
Subcommands:
  organize    Move files to documents/, images/, videos/, archives/
  categories  List supported extensions
Flags (organize):
  --source DIR  Existing directory (required)
  --dry-run     Print all planned moves, without changing any files, including logs
  --help        Show help
Environment: ORGANIZER_LOG (default ./organizer.log); JSONL also goes to stderr.
Example: organizer organize --source '/tmp/my files' --dry-run
Exit: 0 success; 2 arguments; 3 source; 4 destination/collision/move; 5 log I/O.
`

type event struct {
	Time   string `json:"time"`
	Action string `json:"action"`
	Result string `json:"result"`
	Detail string `json:"detail"`
}

type move struct{ source, destination string }

func plan(source string) ([]move, error) {
	entries, err := os.ReadDir(source)
	if err != nil {
		return nil, err
	}
	var moves []move
	for _, entry := range entries {
		info, err := entry.Info()
		if err != nil {
			return nil, err
		}
		if !info.Mode().IsRegular() {
			continue
		}
		category, ok := extensions[strings.ToLower(filepath.Ext(entry.Name()))]
		if !ok {
			continue
		}
		dir := filepath.Join(source, category)
		if stat, err := os.Lstat(dir); err == nil {
			if !stat.IsDir() || stat.Mode()&os.ModeSymlink != 0 {
				return nil, fmt.Errorf("category must be a real directory: %s", dir)
			}
		} else if !errors.Is(err, os.ErrNotExist) {
			return nil, err
		}
		destination := filepath.Join(dir, entry.Name())
		if _, err := os.Lstat(destination); err == nil {
			return nil, fmt.Errorf("destination already exists: %s", destination)
		} else if !errors.Is(err, os.ErrNotExist) {
			return nil, err
		}
		moves = append(moves, move{filepath.Join(source, entry.Name()), destination})
	}
	return moves, nil
}

func execute(args []string, out, stderr io.Writer) int {
	if len(args) == 0 || args[0] == "--help" || args[0] == "-h" {
		fmt.Fprint(out, help)
		if len(args) == 0 {
			return 2
		}
		return 0
	}
	if args[0] == "categories" {
		if len(args) != 1 {
			fmt.Fprintln(stderr, "Error: categories takes no arguments")
			return 2
		}
		keys := make([]string, 0, len(extensions))
		for extension := range extensions {
			keys = append(keys, extension)
		}
		sort.Strings(keys)
		for _, extension := range keys {
			fmt.Fprintf(out, "%s %s\n", extension, extensions[extension])
		}
		return 0
	}
	if args[0] != "organize" {
		fmt.Fprintln(stderr, "Error: unknown subcommand; use --help")
		return 2
	}
	flags := flag.NewFlagSet("organize", flag.ContinueOnError)
	flags.SetOutput(stderr)
	source := flags.String("source", "", "Existing directory (required)")
	dry := flags.Bool("dry-run", false, "Print moves without changes")
	flags.Usage = func() { fmt.Fprint(out, help) }
	if err := flags.Parse(args[1:]); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return 0
		}
		return 2
	}
	if *source == "" || flags.NArg() != 0 {
		fmt.Fprintln(stderr, "Error: --source DIR is required; no positional arguments allowed")
		return 2
	}
	info, err := os.Stat(*source)
	if err != nil || !info.IsDir() {
		fmt.Fprintln(stderr, "Error: source must be an accessible directory")
		return 3
	}
	moves, err := plan(*source)
	if err != nil {
		fmt.Fprintln(stderr, "Error:", err)
		return 4
	}
	for _, item := range moves {
		if *dry {
			fmt.Fprintf(out, "MOVE %q -> %q\n", item.source, item.destination)
			continue
		}
		if err := os.MkdirAll(filepath.Dir(item.destination), 0755); err != nil {
			fmt.Fprintln(stderr, "Error:", err)
			return 4
		}
		// Link+unlink is no-clobber, even if a destination appeared since planning.
		// Files stay on one filesystem; unsupported hard links fail without data loss.
		if err := os.Link(item.source, item.destination); err != nil {
			fmt.Fprintln(stderr, "Error:", err)
			return 4
		}
		if err := os.Remove(item.source); err != nil {
			_ = os.Remove(item.destination)
			fmt.Fprintln(stderr, "Error:", err)
			return 4
		}
		fmt.Fprintf(out, "MOVED %q -> %q\n", item.source, item.destination)
	}
	fmt.Fprintf(out, "files=%d dry_run=%t\n", len(moves), *dry)
	return 0
}

func run(args []string, out, stderr io.Writer) int {
	var log io.Writer = stderr
	dry := false
	for _, arg := range args {
		if arg == "--dry-run" || arg == "-dry-run" || arg == "--dry-run=true" || arg == "-dry-run=true" {
			dry = true
		}
	}
	if !dry {
		path := os.Getenv("ORGANIZER_LOG")
		if path == "" {
			path = "organizer.log"
		}
		file, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0600)
		if err != nil {
			fmt.Fprintln(stderr, "Error: cannot open ORGANIZER_LOG")
			return 5
		}
		defer file.Close()
		log = io.MultiWriter(stderr, file)
	}
	encoder := json.NewEncoder(log)
	write := func(result, detail string) error {
		return encoder.Encode(event{time.Now().UTC().Format(time.RFC3339Nano), "organizer", result, detail})
	}
	if err := write("started", ""); err != nil {
		return 5
	}
	code := execute(args, out, stderr)
	if err := write("finished", fmt.Sprintf("exit_code=%d", code)); err != nil {
		return 5
	}
	return code
}

func main() { os.Exit(run(os.Args[1:], os.Stdout, os.Stderr)) }
