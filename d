 .env.example                                       |   14 [32m+[m
 .gitignore                                         |   24 [32m+[m
 EXPECTED_OUTCOMES_DOCUMENTATION.md                 |    8 [32m+[m[31m-[m
 SYSTEM_DOCUMENTATION.txt                           |  605 [32m++[m[31m--[m
 __pycache__/app.cpython-313.pyc                    |  Bin [31m147381[m -> [32m0[m bytes
 ...est_api_middleware.cpython-313-pytest-9.1.1.pyc |  Bin [31m6492[m -> [32m0[m bytes
 ...st_market_insights.cpython-313-pytest-9.1.1.pyc |  Bin [31m23480[m -> [32m0[m bytes
 ...test_notifications.cpython-313-pytest-9.1.1.pyc |  Bin [31m10981[m -> [32m0[m bytes
 .../test_upload.cpython-313-pytest-9.1.1.pyc       |  Bin [31m964[m -> [32m0[m bytes
 app.py                                             | 3445 [31m--------------------[m
 app/__init__.py                                    |   73 [32m+[m
 app/algorithms/__init__.py                         |    7 [32m+[m
 app/algorithms/crop_recommendation.py              |    5 [32m+[m
 app/algorithms/demand_forecasting.py               |    5 [32m+[m
 app/algorithms/market_analysis.py                  |  189 [32m++[m
 app/algorithms/market_intelligence.py              |    5 [32m+[m
 app/algorithms/reliability_score.py                |   15 [32m+[m
 app/algorithms/supply_detection.py                 |    5 [32m+[m
 app/config.py                                      |   38 [32m+[m
 app/extensions.py                                  |    9 [32m+[m
 app/forms/__init__.py                              |    1 [32m+[m
 app/legacy.py                                      |   71 [32m+[m
 app/models/__init__.py                             |   45 [32m+[m
 app/models/agriculture/__init__.py                 |    5 [32m+[m
 app/models/agriculture/models.py                   |   35 [32m+[m
 app/models/analytics/__init__.py                   |    5 [32m+[m
 app/models/analytics/models.py                     |   19 [32m+[m
 app/models/auth/__init__.py                        |    5 [32m+[m
 app/models/auth/models.py                          |  125 [32m+[m
 app/models/auth/user.py                            |    5 [32m+[m
 app/models/base.py                                 |    8 [32m+[m
 app/models/community/__init__.py                   |    5 [32m+[m
 app/models/community/models.py                     |   27 [32m+[m
 app/models/database.py                             |  697 [32m++++[m
 app/models/inventory/__init__.py                   |    5 [32m+[m
 app/models/knowledge/__init__.py                   |   17 [32m+[m
 app/models/knowledge/models.py                     |   56 [32m+[m
 app/models/marketplace/__init__.py                 |    5 [32m+[m
 app/models/marketplace/models.py                   |   32 [32m+[m
 app/models/messaging/__init__.py                   |    1 [32m+[m
 app/models/transactions/__init__.py                |    1 [32m+[m
 app/models/users/__init__.py                       |    5 [32m+[m
 app/models/verification/__init__.py                |    1 [32m+[m
 app/routes/__init__.py                             |   16 [32m+[m
 app/routes/admin.py                                |  184 [32m++[m
 app/routes/auth.py                                 |  166 [32m+[m
 app/routes/home.py                                 |  902 [32m+++++[m
 app/routes/inventory.py                            |  424 [32m+++[m
 app/routes/knowledge.py                            |  150 [32m+[m
 app/routes/legacy.py                               |    3 [32m+[m
 app/routes/marketplace.py                          |  854 [32m+++++[m
 app/routes/profile.py                              |   43 [32m+[m
 app/services/__init__.py                           |   11 [32m+[m
 app/services/auth_service.py                       |   55 [32m+[m
 app/services/email_service.py                      |    1 [32m+[m
 app/services/geo_service.py                        |   58 [32m+[m
 app/services/market_service.py                     |    5 [32m+[m
 app/services/notification_service.py               |    1 [32m+[m
 app/services/upload_service.py                     |    1 [32m+[m
 {static => app/static}/css/messages.css            |    0
 app/static/js/messages.js                          |  328 [32m++[m
 {static => app/static}/style.css                   |    0
 {templates => app/templates}/404.html              |    0
 {templates => app/templates}/500.html              |    0
 {templates => app/templates}/about.html            |    0
 {templates => app/templates}/add_listing.html      |    0
 {templates => app/templates}/admin.html            |    0
 {templates => app/templates}/admin_knowledge.html  |    0
 {templates => app/templates}/create_post.html      |    0
 {templates => app/templates}/crop_types.html       |    0
 {templates => app/templates}/dashboard.html        |    0
 {templates => app/templates}/edit_inventory.html   |    0
 {templates => app/templates}/edit_post.html        |    0
 {templates => app/templates}/index.html            |    0
 {templates => app/templates}/inventory_table.html  |    0
 {templates => app/templates}/knowledge.html        |    0
 {templates => app/templates}/knowledge_post.html   |    0
 {templates => app/templates}/locations.html        |    0
 {templates => app/templates}/login.html            |    0
 .../templates}/market_intelligence.html            |    0
 .../templates}/market_intelligence_forecast.html   |    0
 .../templates}/market_intelligence_layout.html     |    0
 .../templates}/market_intelligence_price.html      |    0
 .../market_intelligence_recommendations.html       |    0
 .../templates}/market_intelligence_supply.html     |    0
 {templates => app/templates}/marketplace.html      |    0
 {templates => app/templates}/messages.html         |    0
 {templates => app/templates}/my_listings.html      |    0
 app/templates/my_purchases.html                    |   51 [32m+[m
 {templates => app/templates}/profile.html          |    0
 {templates => app/templates}/register.html         |    0
 {templates => app/templates}/top_crop.html         |    0
 {templates => app/templates}/total_harvest.html    |    0
 {templates => app/templates}/trade_listing.html    |    0
 {templates => app/templates}/upload.html           |    0
 app/utils/__init__.py                              |    1 [32m+[m
 app/utils/constants.py                             |    1 [32m+[m
 app/utils/geocoding.py                             |    5 [32m+[m
 app/utils/helpers.py                               |    1 [32m+[m
 app/utils/permissions.py                           |    1 [32m+[m
 app/utils/validators.py                            |    1 [32m+[m
 check_dashboard.py                                 |   13 [31m-[m
 config.py                                          |    3 [32m+[m
 database.db                                        |  Bin [31m86016[m -> [32m0[m bytes
 debug_analytics.py                                 |   33 [31m-[m
 inspect_db.py                                      |   18 [31m-[m
 legacy_root/app.py                                 |   15 [32m+[m
 legacy_root/migrate_sqlite_to_postgres.py          |   98 [32m+[m
 legacy_root/models/user.py                         |   15 [32m+[m
 legacy_root/static/css/messages.css                |  324 [32m++[m
 {static => legacy_root/static}/js/messages.js      |    0
 style.css => legacy_root/static/style.css          |    0
 legacy_root/style.css                              |   18 [32m+[m
 legacy_root/templates/404.html                     |   20 [32m+[m
 legacy_root/templates/500.html                     |   20 [32m+[m
 legacy_root/templates/about.html                   |   32 [32m+[m
 legacy_root/templates/add_listing.html             |  254 [32m++[m
 legacy_root/templates/admin.html                   |  145 [32m+[m
 legacy_root/templates/admin_knowledge.html         |   88 [32m+[m
 legacy_root/templates/create_post.html             |   49 [32m+[m
 legacy_root/templates/crop_types.html              |  206 [32m++[m
 legacy_root/templates/dashboard.html               | 1001 [32m++++++[m
 legacy_root/templates/edit_inventory.html          |   43 [32m+[m
 legacy_root/templates/edit_post.html               |   49 [32m+[m
 legacy_root/templates/index.html                   |   18 [32m+[m
 legacy_root/templates/inventory_table.html         |   17 [32m+[m
 legacy_root/templates/knowledge.html               |  133 [32m+[m
 legacy_root/templates/knowledge_post.html          |   64 [32m+[m
 legacy_root/templates/locations.html               |  235 [32m++[m
 legacy_root/templates/login.html                   |  147 [32m+[m
 legacy_root/templates/market_intelligence.html     |  123 [32m+[m
 .../templates/market_intelligence_forecast.html    |   80 [32m+[m
 .../templates/market_intelligence_layout.html      |  121 [32m+[m
 .../templates/market_intelligence_price.html       |   87 [32m+[m
 .../market_intelligence_recommendations.html       |   72 [32m+[m
 .../templates/market_intelligence_supply.html      |   72 [32m+[m
 legacy_root/templates/marketplace.html             |  523 [32m+++[m
 legacy_root/templates/messages.html                |  204 [32m++[m
 legacy_root/templates/my_listings.html             |  427 [32m+++[m
 legacy_root/templates/my_purchases.html            |   51 [32m+[m
 legacy_root/templates/profile.html                 |  329 [32m++[m
 legacy_root/templates/register.html                |  172 [32m+[m
 legacy_root/templates/top_crop.html                |  209 [32m++[m
 legacy_root/templates/total_harvest.html           |  109 [32m+[m
 legacy_root/templates/trade_listing.html           |  205 [32m++[m
 legacy_root/templates/upload.html                  |  261 [32m++[m
 migrations/README                                  |    1 [32m+[m
 migrations/alembic.ini                             |   50 [32m+[m
 migrations/env.py                                  |  113 [32m+[m
 migrations/script.py.mako                          |   24 [32m+[m
 .../versions/166f046df20c_initial_migration.py     |  533 [32m+++[m
 requirements.txt                                   |   27 [32m+[m[31m-[m
 run.py                                             |   23 [32m+[m
 static/uploads/knowledge/images/images_12.jpg      |  Bin [31m22632[m -> [32m0[m bytes
 templates/my_purchases.html                        |   14 [31m-[m
 test_market_insights.py                            |   24 [32m+[m[31m-[m
 156 files changed, 11928 insertions(+), 3870 deletions(-)
