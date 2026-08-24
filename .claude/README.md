# .claude/

Cấu hình cấp project cho Claude Code khi làm việc trong repo này.

| Thư mục | Dùng cho |
|---|---|
| `agents/` | Subagent riêng của project (file `.md` có frontmatter: name, description, tools, model) |
| `skills/` | Skill riêng của project, mỗi skill 1 thư mục con chứa `SKILL.md` |
| `hooks/` | Script được `settings.json` gọi tại các sự kiện (PreToolUse, PostToolUse...) |
| `doc/` | Tài liệu ngữ cảnh cho Claude đọc khi cần (không phải doc kiến trúc — cái đó ở [../docs](../docs)) |
| `rules/` | Quy ước code/coding convention cho project này — dùng để chia nhỏ thay vì nhồi hết vào [CLAUDE.md](../CLAUDE.md) |

`agents/`, `skills/`, `hooks/` là khái niệm Claude Code nhận trực tiếp. `doc/` và `rules/`
là quy ước riêng của project này — [CLAUDE.md](../CLAUDE.md) ở root nên trỏ vào các file
trong hai thư mục này khi chúng có nội dung, để Claude tự nạp đúng lúc thay vì đọc hết mỗi phiên.

`agents/`, `skills/`, `hooks/` hiện đang trống — chỉ giữ chỗ. `doc/` và `rules/`
đã có nội dung (xem bảng ánh xạ trong [CLAUDE.md](../CLAUDE.md)). `hooks/` cần được khai báo trong
`.claude/settings.json` mới thực sự chạy (dùng skill `update-config` khi cần cấu hình hook).
