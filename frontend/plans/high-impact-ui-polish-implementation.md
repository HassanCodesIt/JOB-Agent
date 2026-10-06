# High-Impact UI Polish Implementation Plan

## Goal

Implement the approved high-impact usability improvements without redesigning the application, changing its information architecture, or removing existing capabilities. The work should make the current interface easier to read, easier to operate, and clearer about what actions do while preserving the existing visual language, page structure, data model, and light/dark themes.

## Scope

Included:

- Readability and functional text sizing
- Interactive target sizing
- Icon action clarity and reusable tooltips
- Tone-correct, dismissible toast feedback
- Dashboard action clarity
- Add Application source/workflow simplification
- Draft Studio inline recipient validation
- Reply Center recovery and back-navigation clarity
- LinkedIn result and row-action hierarchy
- Responsive and light/dark visual review of affected screens

Excluded:

- New backend behavior or persistence
- New application-linking functionality for conversations
- Changes to mock data or business rules
- Broad layout redesigns, new navigation architecture, or new dependencies
- Changes to unrelated page functionality
- Starting another development server; the existing Figma Make server remains authoritative

## Design constraints

- Preserve the current Manrope typography, spacing rhythm, card shapes, semantic color tokens, and light/dark palette.
- Make compact UI more readable without making the interface feel oversized.
- Keep one visually primary action per local action group.
- Preserve all current actions and destinations. Reorganization may move an action into a menu or drawer, but must not remove it.
- Continue using existing shared components from `src/components/ui.tsx`; extend them rather than introducing a second component pattern.
- Preserve keyboard focus visibility, dialog/drawer focus trapping, and existing responsive breakpoints.

## Implementation plan

### 1. Improve shared readability and target sizing

**Files:** `src/index.css`, with no page-specific duplication unless necessary.

1. Raise functional microcopy to a consistent readable floor:
   - Move essential 8px metadata, field hints, timestamps, badges, tabs, and status labels to approximately 10–11px.
   - Move 9–10px button labels, list titles, and form labels to approximately 11–12px.
   - Keep nonessential eyebrow labels compact, but ensure they are not the only source of context.
   - Retain current page-title and card-title sizes unless a local alignment issue appears.
2. Increase line-height slightly for helper text, descriptions, and list previews so the new sizes remain calm rather than dense.
3. Increase `.icon-button`, row action buttons, and input action buttons to at least 36px on desktop while leaving icons near their current 14–18px sizes.
4. Give tabs and compact buttons a minimum target height around 36px.
5. At the existing mobile breakpoints, raise isolated icon controls and critical actions toward 40–44px where space allows.
6. Check that the larger type and controls do not break:
   - Dashboard application columns
   - Draft list rows and composer footer
   - Reply rows
   - LinkedIn job metadata and tabs
   - Settings tabs and form rows

This should be implemented by adjusting existing semantic selectors rather than globally scaling every font size.

### 2. Add reusable, accessible tooltips and clearer icon actions

**Files:** `src/components/ui.tsx`, `src/index.css`, `src/pages/Dashboard.tsx`, `src/pages/ResumeLibrary.tsx`, `src/pages/Settings.tsx`, `src/pages/SentHistory.tsx` as needed.

1. Extend `IconButton` so its existing `label` supplies:
   - `aria-label`
   - Native `title` fallback
   - A styled tooltip exposed on hover and keyboard focus through a `data-tooltip` attribute/pseudo-element.
2. Ensure the tooltip:
   - Does not block clicks
   - Uses theme tokens for background, text, border, and shadow
   - Appears above the control by default
   - Is hidden on coarse-pointer/touch devices where hover does not apply
   - Does not overflow narrow screens where avoidable
3. Add two icons to the shared icon set:
   - `edit` for editing resume records and similar content
   - `back` for backward navigation
4. Replace raw icon-only buttons with `IconButton` where the existing API is sufficient:
   - Dashboard: View source, View last email, Delete
   - Resume Library: Edit primary, Edit role-specific resume, Delete resume
   - Settings: Show/hide API key controls
5. Add a danger-specific class to destructive icon actions so Delete uses the red semantic token on hover/focus without being visually loud at rest.
6. Keep Sent History rows fully clickable; use the eye icon only as a trailing affordance, with row-level accessible text already conveying the action. Do not add a nested button there.

### 3. Make toast feedback tone-correct and dismissible

**Files:** `src/App.tsx`, `src/components/AppShell.tsx`, `src/components/ui.tsx`, `src/index.css`.

1. Add any missing shared icons needed for toast tones, such as warning/error and informational indicators, or map existing icons semantically where appropriate.
2. Replace the current text-symbol toast marker with `Icon`:
   - Success: check
   - Warning: warning/activity
   - Danger: warning/error
   - Violet/neutral: sparkles or information/activity
3. Add an `onDismissToast` callback from `App` to `AppShell`, backed by `setToast(null)`.
4. Add a labeled close `IconButton` to each toast.
5. Structure the toast as icon + message + close action, retaining `role="status"` for non-danger feedback and using an assertive alert role only for danger messages.
6. Update toast styling so border/icon accents reflect the semantic tone in both themes while the surface remains consistent with existing cards.
7. Preserve the existing automatic timeout; manual dismissal is additive and does not change notification generation behavior.

### 4. Clarify Dashboard actions

**Files:** `src/pages/Dashboard.tsx`, `src/index.css`.

1. Rename the page-header action from `Last 30 days` to `View 30-day history` because it navigates to Sent History rather than filtering the dashboard.
2. Add an appropriate directional/history icon without changing the destination.
3. Convert Recent Applications icon actions to shared `IconButton` controls with immediate tooltips.
4. Keep preview actions neutral and style Delete as destructive.
5. Increase spacing between action controls enough to prevent accidental deletion while preserving the current table width.
6. Do not make the metric cards newly clickable in this pass; this avoids introducing navigation behavior not already present. Retain the explicit `Review drafts` button as the actionable exception.

### 5. Simplify Add Application source and workflow choices

**Files:** `src/pages/AddApplication.tsx`, `src/index.css`.

1. Keep the labeled four-step `.workflow-map` as the sole process indicator.
2. Remove the duplicate three-step numeric indicator from the page-header action slot.
3. Keep the upper `intake-choice` as the only source selector for Text, Poster, Upload, and Link.
4. Remove the repeated lower `.source-grid` cards.
5. Move the hidden image file input out of the removed source grid and place it adjacent to the intake selector so Upload behavior is unchanged.
6. Preserve all current handlers:
   - Text focuses the main textarea
   - Poster opens the paste dialog
   - Upload opens the same image picker
   - Link opens the same URL dialog
7. Keep the central quick-start text form, optional resume matching control, one-time instructions, recent drafts, and processing flow unchanged.
8. Remove only CSS that becomes truly unused by this change if it is not shared with another page; otherwise leave shared source-card styles intact.
9. Verify that removing the duplicate source cards shortens the page without leaving awkward vertical gaps at desktop or mobile widths.

### 6. Add inline Draft Studio recipient validation

**Files:** `src/pages/DraftStudio.tsx`, `src/index.css`.

1. Add a ref for the recipient input and a local recipient-error state.
2. On Send with an empty recipient:
   - Do not open the generic status dialog
   - Mark the To address row invalid
   - Show `Add a recipient before sending.` immediately beneath the row
   - Focus the recipient input
3. Clear the error as soon as a nonempty recipient value is entered.
4. Convert the `Recipient needed` readiness chip into a keyboard-operable button only when the recipient is missing; activating it focuses the To field.
5. Preserve all existing send behavior once a recipient exists, including the alternative-resume confirmation and success feedback.
6. Style the error using existing `--red`, `--red-soft`, and border tokens. Keep the address-row dimensions stable enough that the composer does not jump substantially.
7. Preserve the current sticky composer footer and action hierarchy.

### 7. Improve Reply Center recovery and navigation clarity

**Files:** `src/App.tsx`, `src/pages/ReplyCenter.tsx`, `src/components/ui.tsx`, `src/index.css`.

1. Pass the existing app navigation callback into `ReplyCenter`.
2. Replace the downward chevron in `Back to reply center` with the new `back` icon. Keep the same selected-state reset and page behavior.
3. Improve the unlinked-conversation dialog without inventing linking functionality:
   - Explain that the conversation is not linked yet
   - Provide `Close` as the secondary action
   - Provide `Create application` as the primary recovery action, navigating to Add Application
4. Do not add a fake `Link conversation` action because no linking data flow exists in the application.
5. Add a visible `Reply instructions` label around the AI prompt area and move the long example from placeholder-only content into short helper text.
6. Keep the current one-line `Input` and Draft with AI behavior unchanged; this is a labeling/hierarchy adjustment, not a composer redesign.
7. Ensure the Back action and dialog buttons stack cleanly at mobile widths.

### 8. Improve LinkedIn job and result action hierarchy

**Files:** `src/pages/LinkedInJobFinder.tsx`, `src/components/JobDetailsDrawer.tsx`, `src/components/ui.tsx` if a shared menu primitive is warranted, and `src/index.css`.

#### Job-row actions

1. Keep `View details` and `Draft & Apply` visible on each job row.
2. Consolidate LinkedIn post, job, apply, and image links under one compact `Open source` action/menu on the row.
3. Implement the source menu locally or as a small reusable component in `JobDetailsDrawer.tsx` using the existing `JobSourceActions` data flow; do not add a package.
4. Menu behavior must support:
   - Toggle from a labeled button
   - Escape dismissal
   - Outside-click dismissal
   - Keyboard-focusable menu items
   - Opening external URLs with the existing `noopener,noreferrer` behavior
5. Retain the full source actions in the Job Details drawer. On mobile, do not hide all source access; use the same compact source menu above or beside the full-width primary Draft & Apply action.
6. Preserve the current primary-action rule: accepted jobs may retain primary Draft & Apply styling; other jobs keep the current secondary treatment.

#### Result hierarchy

7. Add a compact segmented control immediately before the result area with:
   - `Collected` and the collected count
   - `Filtered` and the accepted/review/rejected result count
8. Show one result panel at a time while retaining the existing panel contents, filters, empty states, and IDs/destinations.
9. Default to Collected.
10. When filtering completes, switch to Filtered and scroll to the result area using the existing smooth-scroll behavior.
11. Update `View collected jobs`, Recent Search `View results`, and empty-state `Run a Search` actions to select the correct result segment before scrolling.
12. Keep Recent Searches in place for this pass; do not add another disclosure interaction while the result hierarchy is changing.
13. Ensure the segmented control scrolls or wraps safely on narrow screens and that both result filter tab groups remain usable.

## Data flow and interface changes

- `AppShell` gains `onDismissToast: () => void`.
- `App` passes `() => setToast(null)` to `AppShell`.
- `ReplyCenter` gains `navigate: (page: PageName) => void`, using the existing `PageName` type and App navigation callback.
- `IconButton` may gain optional positioning or tone props only if necessary; prefer class names to avoid expanding its API unnecessarily.
- `IconName` gains at least `edit` and `back`, plus any explicitly needed toast semantic icon.
- `DraftStudio` adds only local UI state/ref for inline validation; no draft or application type changes.
- `LinkedInJobFinder` adds local `resultView` and source-menu UI state; job/search data types remain unchanged.

## Edge cases and expected behavior

- Long tooltip labels must not cover the triggering control or extend beyond the viewport on common desktop widths.
- Tooltips must appear on keyboard focus and must not be the only accessible label.
- Toast close must be reachable by keyboard and must not trigger surrounding actions.
- Removing Add Application’s duplicate source grid must not remove the hidden upload input or break selecting the same file twice; reset the input value after processing if current browser behavior requires it.
- Draft recipient validation must clear after typing and must not interfere with the resume-suggestion confirmation.
- Reply Center unlinked recovery must close the dialog before navigation.
- LinkedIn source menus must not remain open after choosing an item, switching result sections, opening the drawer, or scrolling to another workflow section.
- Jobs with only one available source still use the same `Open source` affordance for consistency.
- Jobs with no source links should omit the source menu rather than show a disabled empty control.
- Result counts must derive from the same arrays and filter statuses already used by the visible panels.
- Light and dark themes must use semantic tokens; no new theme-specific hardcoded component colors unless a token translation is required.

## Verification

### Automated

1. Run `pnpm build` after the shared component and page changes.
2. Treat a nonzero build exit as a failure and resolve JSX/type issues before reporting completion.
3. Note the existing Vite chunk-size advisory separately if it remains unchanged; do not treat it as a failure.

### Visual and interaction review using the existing supervised preview

Review both light and dark themes at approximately:

- Desktop: 1440px wide
- Tablet/narrow desktop: 820–1024px wide
- Mobile: 375–480px wide

Affected screens and checks:

1. **Global shell**
   - Larger controls still fit the top bar and collapsed sidebar
   - Tooltips render above content and work on keyboard focus
   - Toast tones, close action, and auto-dismiss are clear in both themes
2. **Dashboard**
   - `View 30-day history` reads as navigation
   - Row actions remain aligned; Delete is distinguishable but not overpowering
3. **Add Application**
   - One workflow indicator and one source selector remain
   - Text, paste, upload, and link paths all still open/focus the same controls
   - Layout has no gap where the duplicate source cards were removed
4. **Draft Studio**
   - Empty-recipient Send focuses To and shows an inline error
   - Typing clears the error
   - Normal send and resume-confirmation flows still work
5. **Reply Center**
   - Back icon communicates direction
   - Unlinked conversation offers Close and Create application
   - Reply instructions remain readable and aligned on mobile
6. **LinkedIn Job Finder**
   - Source menu exposes every previously available source action
   - Collected/Filtered switch shows the expected panel and counts
   - Filtering switches to Filtered without losing results
   - Drawer footer keeps Draft & Apply prominent and source access available on mobile
7. **Cross-page readability**
   - Updated small text remains readable without clipping badges, tabs, rows, or form hints
   - Desktop density remains compact and intentional

### Accessibility regression checks

- Tab through all newly changed controls.
- Confirm visible focus rings, accurate accessible labels, and Escape/outside-click behavior for transient menus.
- Confirm dialogs retain focus trapping and return focus on close.
- Confirm destructive actions still require the existing confirmation where applicable.
- Confirm no essential information is available only via color or hover.
