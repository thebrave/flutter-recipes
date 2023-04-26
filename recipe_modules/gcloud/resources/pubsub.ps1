$gcloud_path=$args[0]
$topic=$args[1]
$message_path=$args[2]
$message = Get-Content $message_path -Raw
. $gcloud_path pubsub topics publish $topic --message $message
