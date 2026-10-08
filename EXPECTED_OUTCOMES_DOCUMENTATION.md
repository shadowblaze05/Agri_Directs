# Agri-Direct Expected Outcomes Documentation

## 1. Purpose and scope

Agri-Direct is a web platform for recording harvests, viewing agricultural supply information, connecting farmers and buyers, and supporting better market decisions. This document states what a user should see or be able to achieve on every implemented page. It reflects the current Flask package implementation in `app/` and the templates in `app/templates/`.

### User roles and access

| Role | Expected access |
|---|---|
| Visitor | Can open the public landing page, Login, and Register. |
| Logged-in user | Can manage a profile and own inventory, upload harvest data, view analytics, use the marketplace, exchange messages, and read/interact with published knowledge articles. |
| Admin | Has all logged-in-user access plus the Admin Console and Knowledge Hub administration. |

Protected pages redirect an unauthenticated visitor to Login. Admin-only pages show an access message and return a non-admin user to the Dashboard.

### Mobile and responsive behavior

- Public landing, authentication, marketplace, profile, harvest, dashboard, messages, and admin pages use responsive layouts for phone-sized and tablet viewports.
- On narrow phones, the signed-in sidebar becomes a fixed, horizontally swipeable bottom navigation bar so primary pages remain reachable instead of hiding navigation.
- Main content uses the available phone width; tables can scroll horizontally within their table region, and chat panels and floating chat controls fit the viewport.
- Camera and GPS profile capture still depend on browser permissions and an HTTPS or localhost context.

---

## 2. Account and entry pages

### Home (`/`)

**Expected outcome:** renders the public Agri-Direct landing page, including the latest published Knowledge Hub updates and live database-backed platform metrics. The signed-in portal is available at `/home`; the analytics dashboard is at `/dashboard`.

**Public landing metrics:**

- **Buyers:** counts distinct buyer usernames from accounts whose role is `buyer` together with nonblank `marketplace.buyer_username` values. The `UNION` means a username present in both sources is counted once; purchase usernames without a corresponding user account are still counted.
- **Farm profiles:** counts non-admin user accounts with first name, last name, email, profile picture, profile-photo capture timestamp, verified location, and a nonblank GPS-derived place.
- **Product listings:** counts all marketplace rows except `looking_for` requests, regardless of listing status.
- **Market listings:** counts marketplace rows whose status is `available`, excluding `looking_for` requests.
- **Growth:** compares marketplace listing rows created from the start of the current month through now with rows in the previous month through the same elapsed calendar day and time. It displays the percentage change relative to the previous period; when that period has no listings, the display is `New` if the current period has listings, otherwise `0%`.
- **Knowledge posts:** counts posts with `Published` status only.
- **Process uptime:** elapsed time since this application process started, not a service-availability percentage or an uptime-monitoring result.

The database-backed counts are queried when `/` is rendered. They are not a persisted historical snapshot. These public landing-page metrics are not shown on the signed-in portal at `/home`.

### Legacy landing template (`app/templates/index.html`)

**Implementation note:** this template contains simple links to Upload Harvest Log and View Inventory. The active `/` route renders `public_home.html`, so `index.html` is not the public landing page in the current build.

### Login (`/login`)

**Purpose:** authenticate an existing user.

**Features and expected results:**

- Accepts a username and password.
- Valid credentials create a session and open the Dashboard.
- Invalid credentials keep the user on the page and show an error message.
- Provides a link to Register for a new account.

### Register (`/register`)

**Purpose:** create a standard user account.

**Features and expected results:**

- Collects a unique username and password.
- New accounts are created with the general `user` role; administrator accounts are managed separately.
- A successful registration confirms the result and redirects to Login.
- A duplicate username produces a clear validation message without creating another account.

### Profile (`/profile`)

**Purpose:** maintain the current user’s profile and review personal inventory.

**Features and expected results:**

- Shows account information and whether the user is ready to submit harvest.
- Allows camera-only profile photo capture. Browser GPS is requested separately at capture time; the reverse-geocoded GPS place and the corresponding official PSGC hierarchy are stored separately and both are displayed. Coordinates remain private.
- Requires first name, last name, email, camera-captured profile photo, photo/GPS capture timestamp, and a valid GPS-derived farm location before harvest submission. Phone and bio are optional.
- Displays the user’s inventory grouped by crop, showing the total quantity and most recent receipt date.
- Lets the owner adjust a crop’s total quantity; increases create inventory and reductions remove the newest inventory records first.
- Lets the owner delete all of their inventory for one selected crop after confirmation.
- Rejects invalid quantities and prevents a user from changing another user’s inventory.
- Links to About and Logout.

**Important:** browser geolocation requires user permission and a secure browser context. GPS proximity is not proof of identity, land ownership, crop authenticity, or ownership.

### Camera-captured profile geotag (`/profile/location`)

**Purpose:** update the signed-in user's profile photo and farm reference location from one camera/GPS capture.

- The Profile editor has no file picker: the user starts the browser camera, takes a photo, and grants browser location permission.
- The server validates image content, file size, coordinate ranges, and capture timestamp. It resolves a human-readable place name from GPS coordinates, then matches the place against official PSGC city/municipality, province, and region records. The raw GPS-derived place and PSGC-formatted location are stored separately with the photo and private coordinates.
- If permission is denied, the camera/location services are unavailable, or reverse geocoding fails, the capture is not saved and the user receives an error. If PSGC matching is unavailable, the GPS-derived place is still saved and the user is told there is no PSGC match.
- OpenStreetMap Nominatim receives the submitted coordinates to resolve the approximate place name; this is disclosed in the UI.
- A profile picture's historical file upload or a standalone GPS reading does not satisfy the capture requirement.
- The location reading is a geographic reference only; it does not verify identity or land ownership.

### About (`/about`)

**Purpose:** explain the platform.

**Expected outcome:** presents Agri-Direct’s role as an agricultural supply-chain and market-optimization platform, and describes its inventory, live analytics, and decision-support goals. A Dashboard return button is provided.

### Logout (`/logout` and `/logout/`)

**Expected outcome:** ends the current web session and redirects the user to Login.

---

## 3. Harvest, inventory, and dashboard pages

### Upload Harvest Data (`/upload`)

**Purpose:** add harvest records to the user’s inventory.

**Features and expected results:**

- Supports either a CSV upload or one manual harvest entry in the same form.
- Manual entry provides crop selection/autocomplete, quantity, and optional date; a blank date uses the current date.
- Both CSV and manual harvest submissions are blocked until the account has first/last name, email, a camera-captured profile photo, its GPS capture timestamp, and a valid GPS-derived farm location. Phone and bio remain optional.
- Manual entry accepts a crop/harvest photo (PNG, JPG, or WEBP, up to 5 MB) and requests browser GPS coordinates when available.
- The server validates coordinate ranges and calculates Haversine distance from the user's separately captured profile reference point. The configured maximum is 15 km (15,000 meters); distance at or below the maximum is `within_range`, and greater distance is `outside_range`.
- Missing photo, capture timestamp, harvest coordinates, or verified profile coordinates results in `manual_review`; CSV rows are also marked for manual review because they contain no browser GPS/photo evidence.
- CSV processing accepts `.csv` files and reads `crop_name`, `quantity`, and optional `date_received` fields.
- Each valid record is stored with the signed-in user and their saved profile location.
- Only existing crop names and positive whole-number quantities are added. Invalid rows are skipped and reported without stopping valid rows from being processed.
- A CSV with no valid records reports that nothing was added; a successful import reports success.
- Every successful addition refreshes analytics used by the Dashboard and statistics pages.
- The saved profile address remains the inventory location label; the GPS reference is separate. Records can still be submitted without the reference, but are marked for manual review.
- Crop evidence photos are stored outside the public static directory and are served only to their owner or an administrator.
- JWT `/api/harvest` submissions may include validated GPS coordinates and a capture timestamp; without photo evidence they remain in `manual_review`, while any proximity status and distance are returned separately.

### Dashboard (`/dashboard`)

**Purpose:** provide the main real-time inventory overview.

**Features and expected results:**

- Shows headline cards for total harvest, top crop, crop-type count, and location count. Each card links to its matching detail page.
- Shows crop distribution and location information using charts/maps where data is available.
- Displays recent harvest inventory with farmer, crop, quantity, received date, and location.
- Supports text search and table sorting/filtering for inventory data.
- Provides monthly and yearly offset controls so users can compare the current period with prior months or years.
- Refreshes inventory and statistic data in the browser through the Dashboard data and statistics endpoints, so new data appears without a full manual refresh.
- Includes navigation to Upload, Market Intelligence, Marketplace, Messages, Knowledge Hub, Profile, and Logout.
- Includes a notification control that loads the user’s latest notifications and marks unread notifications as read.
- Includes a quick-message/chat interface with user selection and AgriBot support.
- Shows the Admin Console option only for an administrator.

### Inventory table partial (`app/templates/inventory_table.html`)

**Implementation note:** this is not a standalone route/page. It is the reusable recent-inventory table returned by `/dashboard-data` during Dashboard refreshes. Its expected result is an up-to-date view of recent inventory records without a full dashboard reload.

### Total Harvest (`/total-harvest`)

**Purpose:** show the total recorded quantity across inventory.

**Expected outcome:** displays the overall harvest total and a crop-by-crop total list ordered from the largest total downward, with a button back to the Dashboard.

### Top Crop (`/top-crop`)

**Purpose:** identify the highest-volume crops.

**Features and expected results:**

- Highlights the current top-performing crop.
- Lists the top five crops by accumulated quantity.
- Lets the user choose monthly and yearly offsets; the screen refreshes comparison statistics for the selected periods.
- Provides chart-based comparison information and a Dashboard return action.

### Crop Types (`/crop-types`)

**Purpose:** show the crop variety represented in harvest inventory.

**Features and expected results:**

- Shows the number of distinct crop types.
- Lists crop names with their accumulated harvest quantities, ordered from highest to lowest.
- Provides monthly/yearly offset controls and period-based statistics through the statistics API.
- Provides a Dashboard return action.

### Locations (`/locations`)

**Purpose:** show where recorded supply and users are located.

**Features and expected results:**

- Lists each non-empty inventory location with its accumulated quantity.
- Shows the count of represented locations.
- Maps users with saved locations. The server uses Google geocoding when configured; otherwise it supplies stable fallback coordinates so map markers can still be displayed.
- Provides a Dashboard return action.

### Edit Inventory (`/inventory/edit/<item_id>`)

**Purpose:** edit one inventory record.

**Expected outcome:** shows the selected crop record and permits a positive crop name/quantity update for its owner or an admin. Missing records, non-positive quantities, and unauthorized edits are rejected with feedback and a safe redirect.

### Inventory delete (`/inventory/delete/<item_id>`)

**Expected outcome:** removes the selected inventory record only when the requester is its owner or an admin, then returns to the Dashboard with a result message.

---

## 4. Market intelligence pages and features

### Market Intelligence (`/market-intelligence`)

**Purpose:** translate inventory history into decision-support information.

**Features and expected results:**

- All signed-in users can read a concise market brief on the Dashboard and at `/market-intelligence`; detailed monitoring charts remain administrator-only.
- The signed-in Home page (`/home`) also summarizes the leading crop signal, notable supply update, and suggested next step.
- Presents the leading crop signal, any notable supply issue, and a practical next step in plain language for regular users.
- Labels the brief as inventory-derived guidance, not a guaranteed price, forecast, or confirmed buyer demand.
- Loads market insight data from `/api/market-insights` and forecast data from `/api/forecast`.
- Presents supply/market pressure, estimated price movement, oversupply or undersupply risk, recommendations, and demand forecasts when sufficient harvest data exists.
- Helps a user recognize crops that may have excess supply, limited supply, changing demand, or a stronger market opportunity.
- Uses inventory-derived calculations rather than claiming to display a live external commodity-market feed.

**Current calculation behavior:**

- The market analysis groups inventory by crop and compares current supply against historical/recent supply.
- A supply-pressure threshold of at least `1.35` produces an oversupply risk; a threshold of at most `0.75` produces an undersupply risk.
- The price index uses supply pressure and trend change, and the recommendation model considers demand, price pressure, and seasonal relevance.
- Forecasting uses a linear trend based on available historical values. Results are estimates, not guarantees.

---

## 5. Marketplace pages

### Marketplace (`/marketplace`)

**Purpose:** let users discover, purchase, trade, and rate crop listings.

**Features and expected results:**

- Shows currently available listings with crop, available amount, unit price, seller, seller location, description, expiry information, and seller reliability information.
- Lets users search listings, filter by crop, and change sorting in the browser.
- Provides **Buy** and **Trade** actions for available listings.
- The buy modal calculates the total cost from the selected quantity and blocks requests above available quantity.
- The trade modal lets the user choose one of their available crops and a trade amount.
- Provides shortcuts to create a listing, review My Listings, and review My Purchases.
- Shows a pending-rating prompt for delivered/sold purchases that have not yet been rated; buyers can submit a one-to-five-star rating.
- Sends user-targeted in-app notifications for new messages and marketplace transaction or rating events. The Messages bell shows unread counts and recent notifications, including marketplace updates.
- Administrators can pin a published Agricultural Update; users receive a notification linking directly to it, and pinned posts appear first in the Home and Knowledge Hub feeds.
- Includes the standard navigation, profile menu, and quick chat access.

### Add Marketplace Listing (`/marketplace/add`)

**Purpose:** publish part of the user’s inventory for sale.

**Features and expected results:**

- Presents only crops that the signed-in user currently owns in positive inventory.
- Requires crop, amount, and price; allows unit, description, and listing-expiry period selection.
- Validates positive numerical amount and price.
- Refuses a listing that exceeds the seller’s available quantity.
- Creates an `available` listing with the seller’s profile location and calculated expiry date, then returns to Marketplace with confirmation.
- If the user has no eligible crop inventory, explains that harvest data must be uploaded first and disables listing submission.

### Trade Listing (`/marketplace/trade/<listing_id>`)

**Purpose:** propose a crop-for-crop exchange for an available listing.

**Features and expected results:**

- Shows the target listing and seller/reliability details.
- Allows the requester to select an owned crop and a positive trade amount.
- Validates listing availability, user inventory, and trade amount before processing.
- On a valid trade, updates the relevant inventory/listing transaction records and gives the user clear feedback.
- Offers a return to Marketplace.

### My Listings (`/marketplace/my-listings`)

**Purpose:** let a seller track the listings they created.

**Features and expected results:**

- Shows the current user’s listings and their status, amounts, pricing, dates, buyer/order information, and relevant transaction state.
- Enables the seller to complete an order where the workflow allows it.
- Enables deletion/cancellation of a listing where it remains eligible.
- Provides links back to Marketplace and listing creation.

### My Purchases (`/marketplace/my-purchases`)

**Purpose:** give buyers a record of marketplace purchases.

**Expected outcome:** lists the user’s purchases with crop, seller, quantities, prices, order/delivery information, status, and rating state so they can track completed and pending transactions.

### Marketplace transaction rules

- Buying validates that the listing is available, is not the buyer’s own listing, has not expired, and has enough amount remaining.
- Partial purchases reduce the listing amount; a fully purchased listing changes state to sold.
- Order completion/delivery updates transaction status and contributes to seller reliability tracking.
- Rating is permitted only for the buyer of a delivered/sold listing and only once per transaction.
- The farmer reliability score is the average one-to-five-star rating from confirmed marketplace orders. Profiles show the score, its matching status, and the number of buyer ratings behind it.
- The system tracks total, completed, and cancelled transactions for marketplace users.

---

## 6. Knowledge Hub pages

### Knowledge Hub (`/knowledge`)

**Purpose:** make published farming or market-learning articles available to users.

**Features and expected results:**

- Shows published articles only, newest first.
- Provides keyword search across article titles and content.
- Provides category filtering.
- Shows author, category, date, media preview when present, views, likes, and comment count.
- Opens an individual article when selected.

### Knowledge Article (`/knowledge/<post_id>`)

**Purpose:** read and discuss one article.

**Features and expected results:**

- Shows the full article, including optional uploaded image and video, author, category, and view/like information.
- Increments the article view count when opened.
- Lets a signed-in user toggle a like/unlike action; the displayed like count is updated by the server.
- Lets a signed-in user post a non-empty comment.
- Shows comments and their replies in time order.
- Gives admins a reply form for each comment. Non-admin reply attempts are refused.

### Knowledge Hub Admin (`/admin/knowledge`)

**Purpose:** manage knowledge content; administrator only.

**Features and expected results:**

- Shows totals for all, published, and draft articles.
- Lists articles with title, category, author, status, created date, and views.
- Provides view, edit, delete, and create-new-article actions.
- Deleting an article also removes its dependent likes, comments, and replies.

### Create Article (`/admin/knowledge/create`)

**Purpose:** publish or save an article; administrator only.

**Features and expected results:**

- Requires title and content.
- Lets an admin choose a category and status (Published or Draft).
- Accepts optional image and video uploads.
- Saves the article with the current admin as author and returns to Knowledge Hub Admin with confirmation.

### Edit Article (`/admin/knowledge/edit/<post_id>`)

**Purpose:** update an existing knowledge article; administrator only.

**Features and expected results:**

- Pre-fills existing article values.
- Lets an admin change title, content, category, status, and optionally replace image/video files.
- Keeps existing media when no replacement is provided.
- Rejects missing title/content and handles a missing article with feedback.

---

## 7. Messaging, notifications, and administration

### Messages (`/messages`)

**Purpose:** provide direct user-to-user communication and basic help through AgriBot.

**Features and expected results:**

- Shows existing conversations, last-message previews, timestamps, and full selected-message history.
- Searches user accounts by username to start a new conversation.
- Sends non-empty messages to another user and prevents a user from messaging themselves.
- Creates a notification for the recipient of a direct message.
- Always makes AgriBot available as a contact.
- AgriBot responds to simple questions about uploads, harvests, admin access, profiles, and the About page.
- Uses asynchronous browser requests so conversations can load and send without a full-page navigation.

### Notifications (Dashboard control and `/notifications` API)

**Expected outcome:** the user can open a recent-notifications list from the Dashboard, see new-message alerts, and mark unread notifications as read. The server returns up to the 20 most recent notifications for the current user.

### Admin Console (`/admin`)

**Purpose:** provide an administrative overview; administrator only.

**Features and expected results:**

- Shows all inventory records in date order and supports browser-side search by crop, farmer, or location.
- Lets an admin edit or delete any inventory record.
- Shows crop evidence, proximity status, distance, GPS capture time, and review notes; administrators can approve or reject submissions.
- Shows users with role and marketplace reliability/transaction information.
- Provides links to Dashboard, Knowledge Hub Admin, Audit Log, and Logout.

### Audit Log (`/admin/audit-logs`)

**Purpose:** provide administrators with a searchable activity trail; administrator only.

**Features and expected results:**

- Records write requests throughout the application, authentication activity, and admin-console page access.
- Shows UTC timestamp, actor and role, action, category, request method/path, response status, duration, IP address, user agent, and route parameters.
- Supports text search plus category, method, response, and date-range filters, with newest events first and paginated results.
- Exports the currently matching events to CSV.
- Does not store form bodies, passwords, or authentication tokens; the console provides no delete action for audit entries.

---

## 8. Error pages

### Page Not Found (`404`)

**Expected outcome:** when a route does not exist, the user sees a clear 404 message and a button to return to the Dashboard.

### Internal Server Error (`500`)

**Expected outcome:** when an unhandled server error occurs, the user sees a clear 500 message and a button to return to the Dashboard.

---

## 9. Supporting API and system features

These endpoints support the pages above and are expected to return structured JSON for authenticated browser/API clients where applicable.

| Feature | Endpoint(s) | Expected outcome |
|---|---|---|
| Profile geotag | `POST /profile/location` | Validates and saves the authenticated user's camera photo, browser GPS coordinates, capture timestamp, GPS-derived place, and separately matched PSGC location. |
| Private harvest evidence | `GET /harvest-evidence/<filename>` | Serves the photo only to its submitting farmer or an administrator. |
| Geotag review | `POST /admin/geotag/<item_id>/review` | Admin-only approve/reject action, recording the reviewer and timestamp. |
| JWT access | `POST /token` | Valid credentials receive a token with a 24-hour expiry value. |
| Programmatic harvest entry | `POST /api/harvest` | A valid JWT and positive crop, quantity, and location create a harvest record and refresh analytics. |
| Live inventory table | `GET /dashboard-data` | Returns the rendered recent-inventory table used by Dashboard refreshes. |
| Period statistics | `GET /api/stats` | Returns totals, top crops, crop counts, locations, and monthly/yearly comparisons; supports offset query values. |
| Market intelligence | `GET /api/market-insights`, `GET /api/forecast` | Returns inventory-derived analysis and forecasting data for the Market Intelligence page. |
| Listing details | `GET /api/listing/<listing_id>` | Returns listing data used by marketplace actions. |
| Chat and recipients | `/api/users`, `/api/messages`, `/messages/*`, `/users/search` | Supplies recipients, conversations, histories, search results, and message sending. |
| Notifications | `GET /notifications`, `POST /notifications/mark-read` | Returns recent personal notifications and marks unread entries as read. |

### Data and security expectations

- Web authentication uses Flask sessions; the harvest API uses JWT bearer-token verification.
- Passwords are stored and checked using secure password hashes.
- The app uses PostgreSQL for users, inventory, crops, analytics, marketplace activity, knowledge content, messages, and notifications.
- Server-side validation enforces required fields, positive quantities/prices, ownership rules, and role restrictions for the main operations.
- Uploaded knowledge media is stored beneath the configured upload area; harvest CSV files are saved before being processed.
- Crop evidence images are content-validated, size-limited, stored outside the static web directory, and access-controlled by owner/admin checks.

### Geotag verification limits

- The distance rule is a geographic proximity check only; it does not establish crop authenticity, farmer identity, or ownership of land or produce.
- Browser GPS may be inaccurate or spoofed, and browser access requires permission. Server-side validation checks coordinate ranges but cannot prove that client coordinates came from an unmodified GPS receiver.
- The camera UI removes the file picker, but a browser-submitted image/GPS pair cannot cryptographically prove that a physical camera or genuine GPS sensor produced it.
- Reverse geocoding depends on internet access and OpenStreetMap Nominatim availability; exact coordinates are sent to that service for place-name resolution.
- EXIF is not used as the source of coordinates because it can be removed or changed; the crop photo is supporting evidence only.
- Missing or incomplete location/photo evidence is routed to manual review.

## 10. End-to-end expected user journey

1. A user registers and logs in.
2. The user sets a profile location.
3. The user uploads a CSV or manually records a harvest; the Dashboard totals, crop figures, locations, and analysis update.
4. The user can review supply data, historical comparisons, market intelligence, and location distribution.
5. A farmer can list available inventory in Marketplace; another user can buy or trade for it, complete the order flow, and rate the seller.
6. Users can communicate directly or ask AgriBot for basic guidance.
7. Users can read, like, and comment on published Knowledge Hub content; admins create and moderate that content and manage system inventory.
