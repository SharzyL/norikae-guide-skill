# Norikae Guide Skill

A reusable AI skill for Japan transit route planning and timetable lookup via Yahoo! 乗換案内.

See [SKILL.md](SKILL.md) for full usage reference.

## Install

```bash
npx -y skills@latest add Enter-tainer/norikae-guide-skill --skill norikae-guide --yes --global
```

## Build distributable zip

```bash
python3 scripts/build_skill_zip.py
```

Produces `norikae-guide-skill.zip` containing the skill files ready for distribution.
