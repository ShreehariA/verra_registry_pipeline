-- One row per beneficial owner: every spelling with the same owner_key is one owner. The name shown is the spelling
-- with the most credits, and `spellings` lists them all so a reader can check the merge. 'unspecified' holds the
-- retirements with a blank or placeholder owner.
WITH spelled AS (
    SELECT owner_key, beneficial_owner, sum(quantity) AS credits
    FROM silver.retirements
    GROUP BY ALL
)
SELECT
    owner_key,
    CASE
        WHEN owner_key = 'unspecified' THEN 'Unspecified (blank or placeholder)'
        ELSE first(beneficial_owner ORDER BY credits DESC NULLS LAST, beneficial_owner)
    END AS owner_name,
    string_agg(beneficial_owner, ' | ' ORDER BY credits DESC NULLS LAST, beneficial_owner) AS spellings
FROM spelled
GROUP BY owner_key
ORDER BY owner_key
