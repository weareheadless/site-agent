"""The design, copy and search standard every page build is held to.

One canonical text, used by the owner chat agent and by the delegated build
agent, so a page is judged against the same bar wherever it is authored. It
states behaviour and acceptance, never sample copy: the model writes from the
owner's own context.
"""

DESIGN_AND_CONTENT_CONTRACT = """## Design, copy and search standard

A page is not finished because its content is saved. The owner judges the rendered page. Treat every page build as a design commission, not a content dump.

Before you design, read the site you are extending: the home page composition, the closest sibling page, the presentation components, the CSS custom properties and type scale, and the existing motion setup. Reuse that system — the same fonts, spacing scale, colour tokens, chrome and motion language. Extend it for this page; never introduce a second visual language or a generic section stack.

Composition:
- Give the page a narrative: an opening that establishes who this is for, substantive sections that each do one job, and a closing action.
- Vary rhythm and scale: at least one full-bleed or large-type moment, deliberate whitespace, and a clear hierarchy. Never ship a wall of identical stacked sections.
- When the content schema offers typed section layouts and art direction (hero, gallery, split, centred, and so on), choose them per section instead of leaving a plain stack: a page whose sections all fall back to the default layout has not been designed.
- If the renderer ignores a layout the schema already declares, treat that as a presentation gap to close in the build, not a reason to write plainer content.
- Use real imagery from the site's media library where it earns its place; no decorative filler and no placeholder blocks.
- The page must feel authored for this business, not assembled from a template.

Type and space:
- Work inside the site's existing type scale and spacing rhythm. If the page needs a new step, extend the scale rather than inventing arbitrary values.
- Keep body text readable: comfortable measure, generous line height, and no text over busy imagery without a legible treatment.

Motion:
- Use the motion library the site already loads; do not add a second one.
- Motion must reveal content, never gate it: everything is readable with motion disabled, and `prefers-reduced-motion` removes movement without breaking layout.
- No scroll-jacking, no autoplaying video with sound, and no animation that delays the first meaningful paint.

Responsive and accessible:
- Verify the page at 390px, 768px and 1440px: no horizontal overflow, no clipped headings, no orphaned controls.
- Use semantic landmarks and heading order, one H1, descriptive alt text, visible focus states, and contrast that passes WCAG AA.

Search and copy:
- Title and meta description unique to this page, written for a person deciding whether to read on; canonical URL; Open Graph title, description and image; structured data only if the site already uses it.
- One H1 that says what the page is. Subheadings that carry meaning on their own. Internal links whose text names their destination.
- Copy in the owner's voice and the site's tone: concrete, specific and free of filler. Use only facts the owner supplied or the site already states; never invent credentials, prices, dates, testimonials or claims.
- Every section must earn its place. If a section only restates the previous one, cut it. Read the existing copy on the site first, then match its level of specificity.

Content authority:
- Every visible business string, link and image on an authored page comes from the Payload document, never from a literal in the component. Mark each editable element with the shared binding helper and bind its text, `alt`, `href` and image source to a field the shared content contract declares.
- Do not ship fallback copy for a missing value. Read the value and throw when it is absent, so a broken document fails loudly instead of rendering invented text.
- A script or style body is code, not copy; keep business text out of it.

Delivery:
- Verify what you can: the composition in the source, the type and spacing values, the responsive breakpoints, and the built output. Name what you checked. The owner judges the rendered page, and if the composition still reads as a generic document, it is not done.
"""


def with_design_contract(text: str) -> str:
    """Append the canonical standard to an agent instruction."""
    return text.rstrip() + "\n\n" + DESIGN_AND_CONTENT_CONTRACT
