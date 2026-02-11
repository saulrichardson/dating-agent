# Hinge Agent Tool Catalog

This is the action space the live Hinge agent can choose from each loop.
Actions are only valid when they are currently available on-screen.

| Action ID | Human Equivalent | Description |
| --- | --- | --- |
| `goto_discover` | Tap Discover tab | Navigate to Discover where card decisions happen. |
| `goto_matches` | Tap Matches tab | Navigate to Matches for conversations. |
| `goto_likes_you` | Tap Likes You tab | Navigate to Likes You view. |
| `goto_standouts` | Tap Standouts tab | Navigate to Standouts view. |
| `goto_profile_hub` | Tap Profile tab | Navigate to profile/settings tab. |
| `open_thread` | Tap a match thread | Open a chat thread from matches. |
| `like` | Tap Like | Like the current card item. |
| `pass` | Tap Skip/Pass | Skip the current card item. |
| `send_message` | Type and send message | Send one message in an open thread. |
| `back` | Android back | Dismiss overlays/modals or navigate one level back. |
| `wait` | No tap | Observe only for this loop iteration. |

## Natural-Language Directive Examples

These go into `command_query` in `live_hinge_agent*.json`.

- `Swipe for 40 actions. Dry run.`
- `Go to matches and message for 15 actions.`
- `Live run for 10 minutes, max likes 30, max messages 3.`
- `Only like profiles with quality score above 80.`
- `Don't message, just swipe for 25 actions.`
- `Explore freely for 20 actions. Live run.`
- `Go to matches. Live run for 6 actions.`
- `Open thread now and message for 6 actions.`
- `Force wait for 3 actions. Dry run.`

## Validation Controls

Use `validation` in live config to harden autonomous execution:

```json
{
  "validation": {
    "enabled": true,
    "post_action_sleep_s": 0.8,
    "require_screen_change_for": ["like", "pass", "open_thread", "send_message"],
    "max_consecutive_failures": 4
  }
}
```
