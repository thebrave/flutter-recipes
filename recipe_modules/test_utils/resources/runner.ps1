Write-Host "$args"
$cmd=""
ForEach ($arg in $args) {
  if ($arg.contains(" ")) {
    Write-Host "Processing: $arg"
    $cmd=$cmd, "`"$arg`"" -join " "
  } else {
    $cmd=$cmd, $arg -join " "
  }
}
Write-Host $cmd
iex $cmd | Set-Content $Env:LOGS_FILE -Passthru
exit $LASTEXITCODE