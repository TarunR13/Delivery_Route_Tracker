--basic information that is needed.
SELECT
    COUNT(RouteID)                                              AS total_routes,
    SUM(CASE WHEN Status = 'Completed'      THEN 1 ELSE 0 END)  AS checked_in,
    SUM(CASE WHEN Status = 'MorningCheckIn' THEN 1 ELSE 0 END)  AS morning_check_in,
    SUM(CASE WHEN Status = 'No Show'        THEN 1 ELSE 0 END)  AS unaccounted
FROM routes
WHERE RouteID IS NOT NULL;


--route status organized by driver
SELECT
    DriverName,
    SUM(CASE WHEN Status = 'Completed'      THEN 1 ELSE 0 END) AS completed,
    SUM(CASE WHEN Status = 'MorningCheckIn' THEN 1 ELSE 0 END) AS morning_check_in,
    SUM(CASE WHEN Status = 'No Show'        THEN 1 ELSE 0 END) AS no_show,
    COUNT(*)                                                   AS total
FROM routes
GROUP BY DriverName
ORDER BY total DESC;


--status counts using ALL ROWS (including the suspicious ones)
--this helps me understand the numbers along with the amount of data that is being lost to inaccurately inputted data.
SELECT
    Status,
    COUNT(*) AS routes,
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM routes), 2) AS pct_of_total
FROM routes
GROUP BY Status
ORDER BY routes DESC;


--Average route return time by day of the week. Arrival Hour must not be empty.
SELECT
    DayOfWeek,
    ROUND(AVG(ArrivalHour), 2) AS avg_return_hour,
    COUNT(*)                   AS completed_routes
FROM routes
WHERE Status = 'Completed' AND ArrivalHour IS NOT NULL
GROUP BY DayOfWeek
ORDER BY CASE DayOfWeek
    WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 WHEN 'Wednesday' THEN 3
    WHEN 'Thursday' THEN 4 WHEN 'Friday' THEN 5 WHEN 'Saturday' THEN 6
    WHEN 'Sunday' THEN 7 END;


--Amount of routes per day.
SELECT
    RouteDate,
    COUNT(*) AS routes_that_day
FROM routes
WHERE RouteID IS NOT NULL
GROUP BY RouteDate
ORDER BY routes_that_day DESC;


--No show rate per driver. I made sure to filter out drivers with less than 20 routes.
WITH driver_stats AS (
    SELECT
        DriverName,
        COUNT(*) AS total_routes,
        SUM(CASE WHEN Status = 'No Show' THEN 1 ELSE 0 END) AS no_shows
    FROM routes
    GROUP BY DriverName
    HAVING COUNT(*) >= 20
)
SELECT
    RANK() OVER (ORDER BY 1.0 * no_shows / total_routes DESC) AS rank_worst_first,
    DriverName,
    total_routes,
    no_shows,
    ROUND(100.0 * no_shows / total_routes, 1) AS no_show_pct
FROM driver_stats
ORDER BY rank_worst_first
LIMIT 10;


--how many issues are there in the data and where are they? Good to know so innaccuracies can be traced back.
SELECT 'Missing RouteID' AS issue, COUNT(*) AS rows_affected
FROM routes WHERE DataQualityNotes LIKE '%Missing RouteID%'
UNION ALL
SELECT 'Completed with no arrival time', COUNT(*)
FROM routes WHERE DataQualityNotes LIKE '%no arrival time%'
UNION ALL
SELECT 'Unreadable MorningCheckIn value', COUNT(*)
FROM routes WHERE DataQualityNotes LIKE '%Unreadable MorningCheckIn%';



--More detail on the data gap that was found.
SELECT
    RouteDate,
    COUNT(*) AS routes,
    SUM(CASE WHEN Status = 'No Show' THEN 1 ELSE 0 END) AS no_shows,
    ROUND(100.0 * SUM(CASE WHEN Status = 'No Show' THEN 1 ELSE 0 END) / COUNT(*), 0) AS no_show_pct
FROM routes
WHERE RouteDate BETWEEN '2026-08-28' AND '2026-09-16'
GROUP BY RouteDate
ORDER BY RouteDate;
