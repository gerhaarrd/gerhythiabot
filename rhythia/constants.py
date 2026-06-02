"""Shared constants (filters, countries, bot metadata)."""

FEEDBACK_DISCORD_USERNAME = "arraialdocabo"

MAP_STATUS_CHOICES: list[tuple[str, str]] = [
    ("All", ""),
    ("Ranked", "RANKED"),
    ("Unranked", "UNRANKED"),
    ("Qualified", "QUALIFIED"),
]

COUNTRY_CHOICES: list[tuple[str, str]] = [
    ("Global", ""),
    ("Brazil", "BR"),
    ("United States", "US"),
    ("United Kingdom", "GB"),
    ("Germany", "DE"),
    ("France", "FR"),
    ("Canada", "CA"),
    ("Australia", "AU"),
    ("Japan", "JP"),
    ("South Korea", "KR"),
    ("Philippines", "PH"),
    ("Singapore", "SG"),
    ("Spain", "ES"),
    ("Italy", "IT"),
    ("Poland", "PL"),
    ("Russia", "RU"),
    ("Mexico", "MX"),
    ("Argentina", "AR"),
    ("Chile", "CL"),
    ("Portugal", "PT"),
    ("Netherlands", "NL"),
    ("Sweden", "SE"),
    ("Norway", "NO"),
    ("Finland", "FI"),
]
