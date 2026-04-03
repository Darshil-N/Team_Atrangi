# Design System: Luxury Precision

## 1. Overview & Creative North Star
The Creative North Star for this design system is **"The Clinical Chronometer."** 

This system rejects the cluttered, "dashboard-heavy" aesthetic of traditional medical software in favor of a high-end, editorial experience. It draws inspiration from the horological precision of a Patek Philippe and the hyper-functional clarity of an aerospace flight deck. We move beyond standard templates by embracing **intentional asymmetry** and **expansive negative space**, ensuring that the most critical medical data is framed as a singular, authoritative focal point. This is "Quiet Luxury" applied to life-saving technology: confident, silent, and impossibly sharp.

---

## 2. Colors & Surface Philosophy

The palette is anchored in a "Surgical White" ecosystem, utilizing tonal shifts rather than lines to define the interface.

### The "No-Line" Rule
Explicitly prohibit 1px solid borders for sectioning. Boundaries must be defined solely through background color shifts. For example, a `surface-container-low` section should sit on a `surface` background to create a "pocket" of information. 

### Surface Hierarchy & Nesting
Treat the UI as a series of physical layers—like stacked sheets of frosted glass or fine medical-grade polymer.
- **Base Layer:** `surface` (#f6f9ff)
- **Nested Content:** `surface-container-low` (#eef4fc) for secondary data.
- **Primary Focus:** `surface-container-lowest` (#ffffff) for the main interaction cards to provide maximum "pop."

### The "Glass & Gradient" Rule
To achieve the "Aerospace" feel, use **Glassmorphism** for floating elements (Modals, Popovers). 
- **Recipe:** `surface` color at 70% opacity + 20px Backdrop Blur.
- **Signature Textures:** Use a subtle linear gradient on primary CTAs (`primary` #004ac6 to `primary-container` #2563eb) to give buttons a slight "milled" metallic sheen.

---

## 3. Typography
The typography system is designed to communicate "Luxury Precision" through high-contrast scales and tight letter spacing.

- **The Display Pair:** We use **Manrope** for large-scale data and headlines to provide a modern, technical character, paired with **Inter** for all functional and body text to ensure maximum legibility.
- **Hierarchy of Authority:**
    - **Display-LG (3.5rem):** Reserved for singular, vital metrics (e.g., Heart Rate, AI Confidence Score).
    - **Headline-SM (1.5rem):** Used for section titles, set in Medium weight with -0.02em tracking.
    - **Body-MD (0.875rem):** The workhorse for medical notes.
- **Tracking:** All headers should utilize "Tight Tracking" (-0.01rem to -0.02rem) to mimic high-end editorial typesetting.

---

## 4. Elevation & Depth

Standard shadows are too "dirty" for a surgical environment. We use **Tonal Layering** and **Ambient Light.**

### The Layering Principle
Depth is achieved by "stacking" surface tiers. Place a `surface-container-lowest` card on a `surface-container-low` section to create a soft, natural lift without a single pixel of shadow.

### Ambient Shadows
When an element must float (e.g., a critical diagnostic alert), use an **Ambient Micro-Shadow**:
- **X: 0, Y: 4, Blur: 24px, Spread: 0**
- **Color:** `on-surface` (#161c22) at **4% opacity**. This mimics natural light rather than a digital effect.

### The "Ghost Border"
If a border is required for accessibility, it must be a **Ghost Border**: Use `outline-variant` (#c3c6d7) at **15% opacity**. Never use 100% opaque borders; they disrupt the "Luxury Precision" flow.

---

## 5. Components

### Buttons: The "Precision Trigger"
- **Primary:** Gradient fill (`primary` to `primary-container`), `xl` (1.5rem) corner radius, white text.
- **Secondary:** `surface-container-highest` fill with `primary` text. No border.
- **States:** On hover, increase the gradient intensity. On press, scale the component to 98% to simulate a physical mechanical click.

### Cards & Lists: The "No-Divider" Mandate
Forbid the use of horizontal divider lines. 
- **Separation:** Use 24px of vertical white space (from the Spacing Scale) or a 2-tone background shift.
- **Corner Radius:** All main cards must use `xl` (1.5rem / 24px) to feel soft yet architectural.

### Medical Data Chips
- **Vital Blue:** Use for "Normal/Stable" ranges.
- **Warning Amber:** Use for "Outlier" data (e.g., elevated BP).
- **Alert Crimson:** High-risk indicators.
- **Style:** Semi-transparent background (10% opacity of the color) with a solid-color text for a "light-up" dashboard effect.

### The "AI Pulse" Input Field
- **Default:** `surface-container-low` background, no border.
- **Focus:** Transition background to `surface-container-lowest` and add a 1px "Ghost Border" in `primary`.

---

## 6. Do's and Don'ts

### Do
- **Do** prioritize "Breathing Room." If you think there is enough margin, double it.
- **Do** use `surface-container-lowest` (#FFFFFF) for the most important data point on the screen.
- **Do** use Manrope for numbers. Its geometric nature feels like a calibrated instrument.

### Don't
- **Don't** use pure black (#000000). Always use `on-surface` (#161c22) to maintain the "Obsidian" premium feel.
- **Don't** use 1px dividers to separate list items. Use 8px spacing and tonal shifts instead.
- **Don't** use standard "Drop Shadows." If it looks like a 2015 Material Design card, it is incorrect. The elevation must feel like light hitting a physical surface.