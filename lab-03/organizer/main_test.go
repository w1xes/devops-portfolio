package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func invoke(t *testing.T, args ...string) (int, string) {
	t.Helper()
	t.Setenv("ORGANIZER_LOG", filepath.Join(t.TempDir(), "audit.jsonl"))
	var output, log bytes.Buffer
	code := run(args, &output, &log)
	if !strings.Contains(log.String(), `"result":"finished"`) {
		t.Fatalf("missing audit record: %s", log.String())
	}
	return code, output.String()
}

func create(t *testing.T, path string) {
	t.Helper()
	if err := os.WriteFile(path, []byte("original content"), 0600); err != nil {
		t.Fatal(err)
	}
}

func TestOrganizeAndDryRun(t *testing.T) {
	root := t.TempDir()
	for _, name := range []string{"my report.PDF", "image.png", "movie.mp4", "copy.tar.gz", "unknown.xyz"} {
		create(t, filepath.Join(root, name))
	}
	if err := os.Symlink("my report.PDF", filepath.Join(root, "link.pdf")); err != nil {
		t.Fatal(err)
	}
	code, output := invoke(t, "organize", "--source", root, "--dry-run")
	if code != 0 || strings.Count(output, "MOVE ") != 4 {
		t.Fatalf("dry run: code=%d output=%s", code, output)
	}
	if _, err := os.Stat(filepath.Join(root, "documents")); !os.IsNotExist(err) {
		t.Fatal("dry run created a directory")
	}
	code, _ = invoke(t, "organize", "--source", root)
	if code != 0 {
		t.Fatalf("organize exit %d", code)
	}
	for category, name := range map[string]string{"documents": "my report.PDF", "images": "image.png", "videos": "movie.mp4", "archives": "copy.tar.gz"} {
		data, err := os.ReadFile(filepath.Join(root, category, name))
		if err != nil || string(data) != "original content" {
			t.Fatalf("lost content: %s %v", name, err)
		}
	}
	if _, err := os.Lstat(filepath.Join(root, "link.pdf")); err != nil {
		t.Fatal("symlink was removed")
	}
	code, output = invoke(t, "organize", "--source", root)
	if code != 0 || !strings.Contains(output, "files=0") {
		t.Fatal("repeat was not idempotent")
	}
}

func TestCollisionAndSymlinkCategory(t *testing.T) {
	for _, symlink := range []bool{false, true} {
		root := t.TempDir()
		create(t, filepath.Join(root, "file.pdf"))
		if symlink {
			if err := os.Symlink(t.TempDir(), filepath.Join(root, "documents")); err != nil {
				t.Fatal(err)
			}
		} else {
			if err := os.Mkdir(filepath.Join(root, "documents"), 0700); err != nil {
				t.Fatal(err)
			}
			create(t, filepath.Join(root, "documents/file.pdf"))
		}
		code, _ := invoke(t, "organize", "--source", root)
		if code != 4 {
			t.Fatalf("expected safe refusal, got %d", code)
		}
		if _, err := os.Stat(filepath.Join(root, "file.pdf")); err != nil {
			t.Fatal("original was lost")
		}
	}
}

func TestArguments(t *testing.T) {
	for _, args := range [][]string{{}, {"unknown"}, {"organize"}, {"organize", "--bad"}} {
		code, _ := invoke(t, args...)
		if code != 2 {
			t.Fatalf("args %v returned %d", args, code)
		}
	}
	for _, args := range [][]string{{"--help"}, {"organize", "--help"}, {"categories"}} {
		code, _ := invoke(t, args...)
		if code != 0 {
			t.Fatal("help/categories failed")
		}
	}
	code, _ := invoke(t, "organize", "--source", filepath.Join(t.TempDir(), "missing"))
	if code != 3 {
		t.Fatal("missing source not reported")
	}
}
