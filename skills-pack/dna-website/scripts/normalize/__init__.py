"""dna-website normalizer — turn a dna-website capture into a real
HTML/CSS/JS project that opens in VS Code Live Server and works without
the original SPA runtime.

Pipeline:
   capture/ -> strip_spa -> rewrite_assets -> extract_css ->
               generate_html (AI) -> wire_interactions (AI) ->
               verify (headless, AI self-heal) -> real-project/

Each AI-powered stage uses the Anthropic SDK with prompt caching against
the shared design DNA + content inventory so per-page calls are cheap.
"""

__version__ = "0.1.0"
