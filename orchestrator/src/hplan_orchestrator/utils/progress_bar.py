"""Unicode progress bar rendering utilities for streaming MCP responses."""

import sys
from typing import Optional

# Unicode characters for progress bar
# Use ASCII fallback on Windows to avoid encoding issues in PowerShell
if sys.platform == "win32":
    FILLED_CHAR = "#"  # ASCII fallback
    EMPTY_CHAR = "-"   # ASCII fallback
else:
    FILLED_CHAR = "█"  # U+2588 Full Block
    EMPTY_CHAR = "░"   # U+2591 Light Shade


def render_progress_bar(
    current: int,
    total: int,
    width: int = 50,
    elapsed_seconds: Optional[float] = None,
    action_name: Optional[str] = None,
) -> str:
    """
    Render a Unicode progress bar with optional metadata.
    
    Args:
        current: Current step number (1-indexed)
        total: Total number of steps
        width: Width of the progress bar in characters (default: 50)
        elapsed_seconds: Elapsed time in seconds (optional)
        action_name: Name of current action (optional)
    
    Returns:
        Formatted progress string, e.g.:
        "[██████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░] 52% | Step 320/610 | 62.3s | aspirate"
    
    Examples:
        >>> render_progress_bar(50, 100)
        '[█████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░] 50% | Step 50/100'
        
        >>> render_progress_bar(50, 100, elapsed_seconds=30.5, action_name="aspirate")
        '[█████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░] 50% | Step 50/100 | 30.5s | aspirate'
    """
    # Calculate percentage and filled width
    percent = int((current / total) * 100) if total > 0 else 0
    filled = int((current / total) * width) if total > 0 else 0
    
    # Build progress bar
    bar = FILLED_CHAR * filled + EMPTY_CHAR * (width - filled)
    
    # Build components
    parts = [f"[{bar}] {percent}%", f"Step {current}/{total}"]
    
    if elapsed_seconds is not None:
        parts.append(f"{elapsed_seconds:.1f}s")
    
    if action_name:
        # Truncate long action names
        display_name = action_name[:30] + "..." if len(action_name) > 30 else action_name
        parts.append(display_name)
    
    return " | ".join(parts)


def render_completion_message(
    total_steps: int,
    elapsed_seconds: float,
    success: bool = True,
) -> str:
    """
    Render a completion message after execution finishes.
    
    Args:
        total_steps: Total steps executed
        elapsed_seconds: Total execution time
        success: Whether execution succeeded
    
    Returns:
        Completion message string
    
    Examples:
        >>> render_completion_message(100, 60.0, success=True)
        '✅ [##################################################] 100% | Step 100/100 | 60.0s | complete'

        >>> render_completion_message(50, 30.0, success=False)
        '❌ [#########################-------------------------] 100% | Step 50/50 | 30.0s | failed'
    """
    # Use ASCII fallback on Windows
    if sys.platform == "win32":
        status_emoji = "[OK]" if success else "[FAIL]"
    else:
        status_emoji = "✅" if success else "❌"
    status_text = "complete" if success else "failed"
    bar = FILLED_CHAR * 50 if success else (FILLED_CHAR * 25 + EMPTY_CHAR * 25)
    
    return f"{status_emoji} [{bar}] 100% | Step {total_steps}/{total_steps} | {elapsed_seconds:.1f}s | {status_text}"

