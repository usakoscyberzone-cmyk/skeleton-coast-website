# Skeleton Coast Growth Dashboard — Version 1 Design

Date: 2026-09-06
Status: Approved design draft for user review
Owner: Skeleton Coast Fishing Adventures & Tours

## 1. Purpose

Build a private hybrid YouTube growth system for the Skeleton Coast Fishing Adventures & Tours channel. The system should improve real watch time, returning viewers, Browse/Suggested distribution, subscriber conversion, and second-video viewing by helping package videos better, create supporting assets, analyze channel performance, and recommend next actions.

The system must not fabricate views, automate engagement, or manipulate YouTube metrics. It should optimize real audience behavior through better packaging, retention, funnel design, and data-informed recommendations.

## 2. Version 1 Boundaries

Version 1 supports one YouTube channel only: Skeleton Coast Fishing Adventures & Tours.

The app may analyze data and generate recommendations automatically, but it must not automatically change titles, thumbnails, descriptions, playlists, publishing settings, or other YouTube configuration.

The Windows helper may read and analyze local files and create new assets, but it must not modify DaVinci Resolve projects or timelines automatically.

## 3. Architecture

Version 1 is a hybrid system with two primary components.

### 3.1 Windows Helper

Runs on the user's Windows PC and watches the master folder:

`I:\YouTube Projects`

Responsibilities:
- Detect new project folders.
- Scan supported video, audio, image, subtitle, and metadata files.
- Read technical media metadata such as duration, resolution, frame rate, codec, and timestamps.
- Create standard output folders when missing.
- Produce asset files requested by the dashboard.
- Generate or export thumbnails, cut lists, captions, metadata text, and project reports.
- Send project metadata and generated-analysis results to the web dashboard.

The helper must not modify DaVinci Resolve projects.

### 3.2 Web Dashboard

Runs in a browser and connects to the Skeleton Coast YouTube channel using approved YouTube APIs.

Responsibilities:
- Display current channel and video performance.
- Organize local projects discovered by the Windows helper.
- Provide packaging recommendations.
- Track Shorts-to-long-form funnels.
- Compare analytics across video topics and formats.
- Generate action recommendations.
- Maintain a learning library based on the channel's own historical performance.

## 4. Project Folder Structure

Each project folder under `I:\YouTube Projects` should use the following output structure:

```text
<Project Name>\
    Thumbnails\
    Shorts\
    Captions\
    Metadata\
    Analytics\
    Exports\
```

The app may create these folders automatically if they are missing.

## 5. Dashboard Screens

### 5.1 Home Dashboard

Shows:
- Channel views.
- Watch hours.
- Subscribers gained.
- Current realtime views.
- Top current long-form video.
- Top current Short.
- Traffic-source split.
- Active recommendations.
- A Green / Amber / Red status indicator for important current videos.
- A concise "What should I do next?" action panel.

Example actions:
- Leave current thumbnail unchanged.
- Publish a specific Short.
- Prepare a follow-up video.
- Review retention after a defined sample threshold.

### 5.2 Projects

Each folder under `I:\YouTube Projects` appears as a project card.

Each card may show:
- Long-form publish state.
- Number of planned/completed Shorts.
- Current thumbnail status.
- Analytics connection state.
- Latest recommendation.

### 5.3 Packaging Lab

For each video, the Packaging Lab supports:
- Multiple title candidates.
- Multiple thumbnail candidates.
- Combined title + thumbnail evaluation.
- Hook suggestions.
- SEO description.
- Tags/keywords.
- Pinned comment.
- Chapters.
- Playlist recommendations.
- Next-video CTA recommendations.

Scoring criteria may include:
- Curiosity.
- Clarity.
- Search relevance.
- Audience fit.
- Uniqueness.
- Title/thumbnail complementarity.

A score must always be accompanied by a plain-language explanation. The app must not present a score as objective truth.

### 5.4 Retention Screen

For published videos, ingest retention data when available and mark:
- Opening retention.
- First significant drop.
- Strong replay or high-interest sections.
- Slow sections.
- Strong ending sections.
- Possible Short candidates.

For unpublished videos, the Windows helper may estimate weak sections from scene duration, silence, speech density, and visual change. These must be labeled as predictions, not measured audience behavior.

### 5.5 Shorts Funnel

Each long-form project can have multiple Shorts with distinct strategic roles.

For each Short, track:
- Hook type.
- Source timestamps.
- Target duration.
- On-screen text.
- CTA.
- Publish status.
- Views.
- Subscribers gained.
- Traffic sources.
- Long-video funnel performance where measurable.

Shorts may be classified as:
- Discovery.
- Conversion.
- Winner.

### 5.6 Analytics

Track and compare:
- Impressions.
- CTR.
- Views.
- Average view duration.
- Average percentage viewed.
- Watch time.
- Subscribers gained.
- Subscriber conversion rate.
- Browse traffic.
- Suggested traffic.
- Search traffic.
- External traffic.
- Shorts Feed traffic.
- Returning viewers.
- Views after 1 hour, 24 hours, and 7 days.

Topic groups should include at minimum:
- Fishing.
- Namibia travel.
- Angola.
- History.
- 4x4.
- Current events.

### 5.7 Recommendations

Recommendations must be prioritized and sparse.

Each recommendation must include:
- Action.
- Reason.
- Confidence.
- Data used.

Example:

Action: Leave thumbnail unchanged.
Reason: Browse traffic is increasing while realtime views remain strong.
Confidence: High.
Data used: current impressions, CTR, traffic-source share, realtime trend.

The engine should recommend one packaging change at a time when testing is needed.

### 5.8 Learning Library

The Learning Library stores channel-specific patterns such as:
- Thumbnail wording performance.
- Hook performance.
- Topic performance.
- Shorts duration performance.
- Subscriber conversion by format.
- Browse/Suggested response patterns.
- Audience differences by geography where available.
- Long-form follow-up performance.

The app should prefer the channel's own historical baselines over generic creator-industry benchmarks whenever enough channel data exists.

## 6. Recommendation Engine

### 6.1 State Model

Each tracked video can be placed in one of three states:

Green — Leave it alone.
- Distribution is expanding or performance is healthy.
- Do not interfere with active testing.

Amber — Watch closely.
- Some metrics are weakening, but evidence is not yet strong enough to justify a change.

Red — Test a change.
- Enough evidence shows that packaging or another controllable factor is underperforming.

### 6.2 Guardrails

The recommendation engine must account for:
- Video age.
- Sample size.
- Traffic source.
- Whether distribution is expanding.
- External traffic spikes.
- Video type.
- Video length.
- Topic category.
- Historical channel performance.

It must not recommend title/thumbnail changes based on very small samples.

### 6.3 Retention Recommendations

Compare a video's retention against similar Skeleton Coast videos by length, format, and topic.

Possible outputs:
- Strong opening.
- Weak first 30 seconds.
- Mid-video drop.
- High-interest section.
- Suggested future edit improvement.
- Suggested Short extraction point.

### 6.4 Shorts Recommendations

Evaluate:
- Viewed vs swiped away.
- Average percentage watched.
- Replays.
- Shares.
- Subscribers.
- Traffic sources.
- Long-form funnel value where measurable.

Do not judge Shorts by views alone.

### 6.5 Topic and Follow-up Recommendations

The app should identify outlier topics and recommend follow-ups when a topic significantly outperforms comparable channel content.

This is especially useful for time-sensitive or high-interest stories, where a follow-up opportunity can expire quickly.

## 7. Asset Generation

Version 1 may create:
- 16:9 thumbnail PNG files.
- 9:16 thumbnail/social PNG files.
- Shorts/Reels cut lists with exact source timestamps.
- Caption/subtitle files.
- YouTube titles, descriptions, tags, and pinned comments.
- Facebook captions.
- Instagram captions.
- Chapter files.
- Project metadata summaries.
- Performance reports.

All generated files should be saved inside the relevant project folder.

## 8. YouTube Integration

The dashboard connects only to the Skeleton Coast Fishing Adventures & Tours YouTube channel in Version 1.

The integration should be read-only for analytics and channel/video metadata unless the user explicitly approves a later expansion.

Version 1 must not:
- Upload videos automatically.
- Publish videos automatically.
- Change titles automatically.
- Change thumbnails automatically.
- Change descriptions automatically.
- Change playlists automatically.
- Modify other channel settings automatically.

## 9. Explicitly Out of Scope for Version 1

- Multiple channels.
- Public user accounts.
- Billing/subscriptions.
- Selling the software to other creators.
- Automatic engagement.
- Fake views or artificial watch-time generation.
- Automatic YouTube changes.
- Automatic DaVinci Resolve edits.
- Automatic timeline modification.
- Complex creator-marketplace features.

## 10. Success Criteria

Version 1 is successful if it reliably helps the user make better decisions that improve real audience behavior, especially:
- Real watch time.
- Returning viewers.
- Browse/Suggested traffic.
- Subscriber conversion.
- Second-video viewing.
- Better Short-to-long-form funnel performance.

A secondary success criterion is workflow efficiency: the user should spend less time manually organizing assets, checking scattered analytics, and deciding what to do next.

## 11. Core Product Principle

The dashboard should answer one question clearly whenever it is opened:

**What should I do next?**

It should prefer a small number of evidence-based actions over large amounts of raw analytics.
