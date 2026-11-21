# Tooling: rust-anything

## Installed version

`rust-anything` 2.0.2, installed from crates.io with a pinned version:

```sh
cargo install --locked --version 2.0.2 --root ~/.local rust-anything
```

The binary is `~/.local/bin/rust-anything` (already on `PATH`).

## OpenCode integration

The active OpenCode config is `~/.config/opencode/opencode.jsonc` (note the
`.jsonc` extension). `rust-anything setup` writes `opencode.json`, which would
create a second config file. To keep the existing config, the MCP server was
added with OpenCode itself:

```sh
opencode mcp add --global rust-anything -- /home/baka/.local/bin/rust-anything mcp
```

Final entry:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "rust-anything": {
        "type": "local",
        "command": ["/home/baka/.local/bin/rust-anything", "mcp"]
      }
    }
  }
}
```

The workflow skill is installed at
`~/.config/opencode/skills/rust-anything/{SKILL.md,whole-app.md}`.

Verify:

```sh
opencode mcp list          # rust-anything connected
rust-anything --version
```

`rust-anything doctor` may report `OpenCode mcp: missing` because it looks for
`opencode.json`; that is a tool-side path assumption, not a broken setup. The
functional check is `opencode mcp list`.

## How we use it

We use the **unit-level** workflow:

```
analyze → bridge → record → port src/port.rs → build → diff → shadow → gate
```

We do **not** use `app_front_door` / `app_lift`: the target UI is C++/Qt, not a
pure Rust CLI or server. The PyO3 bridge is a transition mechanism for proving
core behavior inside the existing Python app.

## Commands

```sh
rust-anything analyze . --lang python --whole-app
rust-anything map .
rust-anything bridge . metadata_normalize.py
rust-anything record rust/metadata-normalize-rs --inputs rust/metadata-normalize-rs/custom_cases.jsonl
rust-anything build rust/metadata-normalize-rs
rust-anything diff rust/metadata-normalize-rs
rust-anything gate rust/metadata-normalize-rs
```

## Caution

`record` executes the original code, including code that may touch files,
databases or the network. Run it on a copy of the project with test data. For
OctoBeat, point it at temporary database copies and never at the live
`music.db`.
