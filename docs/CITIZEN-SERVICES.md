# Citizen services

## Community updates and donations

Administrators create news as drafts, verify them, and publish them. Only published updates are shown to non-administrators. Verification records the reviewing administrator; operators must verify the actual content and source before publication.

Administrators may create and close donation campaigns. Signed-in users may record money or supplies as pledges, and administrators can mark a pledge received or rejected with a note. **This application does not collect money, process payments, verify receipts automatically, or add pledged supplies to inventory.** Money pledges are recorded in INR; confirmation is a manual administrative action. Pledges are visible to their owner and administrators only.

The citizen dashboard links to alerts, shelter search, community updates and safety references. Shelter cards are not a distance ranking. Safety reference summaries are marked as awaiting review and must not replace current official instructions. Emergency contacts link to their listed sources; operators should verify them before deployment and maintain them as official information changes.

## Photo and voice attachments

After submitting a report, its citizen owner can attach up to five photos or recorded audio files, each no larger than 3 MiB. JPEG, PNG, WebP, WAV, Ogg and WebM signatures are accepted. Attachments are stored in the database and are readable by the report owner, the assigned response team, the explicitly assigned investigation team and administrators. Closed, cancelled or rejected reports cannot receive new attachments. The browser interface selects an existing file; it does not record or transcribe audio. File contents may include sensitive incident information and must be protected by the same access and backup policies as the database.

## Password recovery

Password recovery is unavailable until the deployment operator configures a working SMTP server. Set the following values in the private environment (or private `.env` file):

```text
RECOVERY_SMTP_HOST=your-smtp-host
RECOVERY_SMTP_PORT=587
RECOVERY_FROM_EMAIL=sender@example.org
RECOVERY_BASE_URL=https://your-resq-origin.example
RECOVERY_SMTP_USER=your-smtp-user
RECOVERY_SMTP_PASSWORD=your-private-smtp-password
```

The SMTP server must support STARTTLS. The user/password pair is optional only for a trusted SMTP server that accepts unauthenticated sending. `RECOVERY_BASE_URL` must be the exact public HTTPS origin; HTTP is accepted only for localhost development. Configure and protect SMTP credentials without committing them. An operator must verify actual delivery on the target deployment: the automated tests replace the SMTP transport and do not send real mail. Recovery tokens are random, stored only as SHA-256 hashes, expire after 30 minutes, and are single-use; the reset revokes existing bearer sessions. Requests return the same message for known and unknown accounts, and at most three links per account are issued per hour. Failed delivery invalidates the link. The recovery link carries its token in a URL fragment that browser JavaScript clears before submitting it. If SMTP is not configured, the interface says recovery is unavailable rather than claiming an email was sent.

## Similar report review

On an administrator's report detail, possible duplicates are candidate reports with the same normalized written location and similar message text among the latest 1,000 reports. This is a limited review aid: a match does not establish duplication and an absent match does not prove uniqueness. The tool never merges, hides or changes reports.

## Assistant conversations

Assistant questions and answers are saved as private account-owned conversations; administrators do not receive cross-account history access. A user can reopen earlier conversations or start a new one. For model-backed answers, up to four recent question-and-answer pairs from that conversation may be sent to the configured model for context. Prior locally retrieved report status and summary pairs are excluded from model context; case status and report summaries are handled locally with incident permissions. If the configured model is unavailable, the local fallback answers only the latest question and says so. Past responses and shelter results may be stale: recheck live status and current official information before acting. Choosing Gemini as the assistant provider sends eligible conversation content to that provider; local Ollama keeps model inference local. Test data and account conversations should be protected in database backups.
