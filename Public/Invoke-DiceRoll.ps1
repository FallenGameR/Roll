<#
.SYNOPSIS
    Rolls dice expressions piped in as strings (e.g. "2d6+3", "4xd20").

.DESCRIPTION
    Parses strings like "25 x 5d6 + 2" (25 repetitions of 5d6+2) or
    "2xd20 vs 15" (roll d20 twice against AC 15, highlighting hit/miss),
    with automatic crit hit/miss detection and coloring for d20 rolls.

    Kept as a pipeline filter (not a param-based function) so the original
    usage style keeps working unchanged:
        "25 x 5d6 + 2" | Invoke-DiceRoll
        "2xd20 vs 15"  | roll -CritHits 19, 20

.PARAMETER CritHits
    Extra values (besides the natural max roll) that count as a critical
    hit on a d20. Defaults to just the natural maximum (e.g. 20).

.EXAMPLE
    "25 x 5d6 + 2" | Invoke-DiceRoll
.EXAMPLE
    "2xd20 vs 15" | roll -CritHits 19, 20
#>
filter Invoke-DiceRoll( $CritHits = @() )
{
    function e( $c, $t ){ "`e[$($c)m$($t)`e[0m" }

    $parsed = $psitem -match "^((?<n>\d+)\s*x\s*)?(?<dices>\d+)?D(?<sides>\d+)(\s*\+\s*(?<mod>\d+)\s*)?(\s+VS\s+(?<ac>\d+))?$"
    if( -not $parsed ){ throw "Dont know how to parse $psitem" }

    $n = [int] $Matches["n"]
    $dices = [int] $Matches["dices"]
    $sides = [int] $Matches["sides"]
    $mod = [int] $Matches["mod"]
    $ac = [int] $Matches["ac"]
    if( $n -eq 0 ){ $n = 1 }
    if( $dices -eq 0 ){ $dices = 1 }
    if( -not $CritHits ){ $critHits = @($sides)}

    $sum = 0
    foreach( $i in 1..$n )
    {
        $line = "$(e 90 '{0,2}:') $($dices)$(e 90 d)$($sides)" -f $i
        if( $mod ){ $line += " + $mod"}

        $total = 0
        $critMiss = $false
        $critHit = $false
        foreach( $d in 1..$dices )
        {
            $roll = Get-Random -Min 1 -Max ($sides+1)
            if( $sides -eq 20 )
            {
                if( $roll -eq 1         ){ $critMiss = $true }
                if( $roll -in $critHits ){ $critHit = $true }
            }
            $roll += $mod
            $total += $roll
        }

        $line += " $(e 90 =) $total"
        if( $critMiss )             { $line += " $(e 93 CRIT) $(e 31 miss)"}
        elseif( $critHit )          { $line += " $(e 93 CRIT) $(e 32 hit)" }
        elseif( $ac )
        {
            if( $total -ge $ac )    { $line += " $(e 32 hit)" }
            else                    { $line += " $(e 31 miss)"}
        }

        $sum += $total
        Write-Host $line
    }

    if( ($sides -ne 20) ){ Write-Host "`n$(e 90 Total) $sum" }
}

Set-Alias -Name roll -Value Invoke-DiceRoll
