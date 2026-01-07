
# Run tests using defaults from pytest.ini
Write-Host "Running Tests..."
& .venv\Scripts\pytest.exe

if ($LASTEXITCODE -eq 0) {
    Write-Host "Tests Passed. Updating Badge..."
    # Generate badge from coverage
    & .venv\Scripts\coverage-badge.exe -o coverage.svg -f
    
    # Remove decimals (e.g. 90.4% -> 90%)
    (Get-Content coverage.svg) -replace '([0-9]+)\.[0-9]+%', '$1%' | Set-Content coverage.svg
    
    Write-Host "Badge updated: coverage.svg"
} else {
    Write-Host "Tests Failed. Badge not updated."
}
