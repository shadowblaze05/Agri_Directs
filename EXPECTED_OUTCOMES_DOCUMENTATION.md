# Agri-Direct Expected Outcomes Documentation

## 1. Purpose and scope

Agri-Direct is a web platform for recording harvests, viewing agricultural supply information, connecting farmers and buyers, and supporting better market decisions. This document states what a user should see or be able to achieve on every implemented page. It reflects the current Flask implementation in `app.py` and the templates in `templates/`.

### User roles and access

| Role | Expected access |
|---|---|
| Visitor | Can open Login and Register. The home page redirects visitors to Login. |
| Logged-in user | Can manage a profile and own inventory, upload harvest data, view analytics, use the marketplace, exchange messages, and read/interact with published knowledge articles. |
| Admin | Has all logged-in-user access plus the Admin Console and Knowledge Hub administration. |

Protected pages redirect an unauthenticated visitor to Login. Admin-only pages show an access message and return a non-admin user to the Dashboard.

---

## 2. Account and entry pages

### Home (`/`)

**Expected outcome:** acts as a smart entry point. A signed-in user is sent to the Dashboard; a visitor is sent to Login. It does not display a separate landing screen.

### Legacy landing template (`templates/index.html`)

**Implementation note:** this template contains simple links to Upload Harvest Log and View Inventory, but the active `/` route currently redirects to Login or Dashboard instead of rendering it. It is therefore not an active user-facing page in the current build.

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

**Purpose:** maintain the current user’s location and review personal inventory.

**Features and expected results:**

- Shows the current account information and location controls, including Philippine Standard Geographic Code (PSGC) location selection in the interface.
- Saves the selected location to the user profile.
- Displays the user’s inventory grouped by crop, showing the total quantity and most recent receipt date.
- Lets the owner adjust a crop’s total quantity; increases create inventory and reductions remove the newest inventory records first.
- Lets the owner delete all of their inventory for one selected crop after confirmation.
- Rejects invalid quantities and prevents a user from changing another user’s inventory.
- Links to About and Logout.

**Important expected condition:** a user must save a profile location before the system accepts harvest uploads.

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
- CSV processing accepts `.csv` files and reads `crop_name`, `quantity`, and optional `date_received` fields.
- Each valid record is stored with the signed-in user and their saved profile location.
- Only existing crop names and positive whole-number quantities are added. Invalid rows are skipped and reported without stopping valid rows from being processed.
- A CSV with no valid records reports that nothing was added; a successful import reports success.
- Every successful addition refreshes analytics used by the Dashboard and statistics pages.
- The page prevents uploads until the user has set a profile location.

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

### Inventory table partial (`templates/inventory_table.html`)

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
- The system tracks total, completed, and cancelled transactions, plus a reliability score/status for marketplace users.

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
- Shows users with role and marketplace reliability/transaction information.
- Provides links to Dashboard, Knowledge Hub Admin, and Logout.

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
- The app uses SQLite for users, inventory, crops, analytics, marketplace activity, knowledge content, messages, and notifications.
- Server-side validation enforces required fields, positive quantities/prices, ownership rules, and role restrictions for the main operations.
- Uploaded knowledge media is stored beneath the configured upload area; harvest CSV files are saved before being processed.

## 10. End-to-end expected user journey

1. A user registers and logs in.
2. The user sets a profile location.
3. The user uploads a CSV or manually records a harvest; the Dashboard totals, crop figures, locations, and analysis update.
4. The user can review supply data, historical comparisons, market intelligence, and location distribution.
5. A farmer can list available inventory in Marketplace; another user can buy or trade for it, complete the order flow, and rate the seller.
6. Users can communicate directly or ask AgriBot for basic guidance.
7. Users can read, like, and comment on published Knowledge Hub content; admins create and moderate that content and manage system inventory.
