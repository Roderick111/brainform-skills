// ============================================================
// N8N CODE NODES FOR OUTREACH DB
// ============================================================

// ------------------------------------------------------------
// DOMAIN NORMALIZATION + FIELD MAPPING
// Use in Code node before upsert_company Execute Query
// ------------------------------------------------------------
const normalizeDomain = (raw) => {
  if (!raw) return null;
  return (
    raw
      .trim()
      .toLowerCase()
      .replace(/^https?:\/\//, "")
      .replace(/^www\./, "")
      .replace(/\/$/, "")
      .replace(/\/.*$/, "")
      .trim() || null
  );
};

const items_mapped = items.map((item) => {
  return {
    json: {
      ...item.json,
      clean_domain: normalizeDomain(
        item.json.company_domain || item.json.domain || "",
      ),
    },
  };
});

return items_mapped;

// ------------------------------------------------------------
// GMAIL REPLY CLASSIFIER
// Use in Code node after Gmail Get Many node
// Classifies each email and extracts sender name/email/domain
// ------------------------------------------------------------
const email_items = $input.all();

return email_items.map((item) => {
  const email = item.json;
  const from = (email.From || "").toLowerCase();
  const subject = (email.Subject || "").toLowerCase();
  const snippet = (email.snippet || "").toLowerCase();

  let status = "replied";
  let sentiment = "negative";
  let notes = "";

  // BOUNCED — delivery failure
  if (
    from.includes("postmaster@") ||
    from.includes("mailer-daemon") ||
    subject.includes("undeliverable") ||
    subject.includes("delivery failed") ||
    subject.includes("mail delivery") ||
    snippet.includes("couldn't be delivered") ||
    snippet.includes("wasn't found at")
  ) {
    status = "bounced";
    sentiment = null;
    notes = "email bounced - address invalid or restricted";
  }

  // ANTISPAM — mailinblack or domain verification
  else if (
    from.includes("mailinblack") ||
    from.includes("invitations.mailinblack") ||
    from.includes("antispam") ||
    snippet.includes("protégée par la solution protect") ||
    snippet.includes("protégée par une solution de vérification")
  ) {
    status = "sent_1"; // keep in pipeline
    sentiment = null;
    notes = "mailinblack antispam - treated as sent";
  }

  // AUTO REPLY — out of office, maternity, sabbatical
  else if (
    subject.includes("automatic reply") ||
    subject.includes("réponse automatique") ||
    subject.includes("message d'absence") ||
    subject.includes("grace is away") ||
    snippet.includes("currently out of the office") ||
    snippet.includes("currently away from my desk") ||
    snippet.includes("congé maternité") ||
    snippet.includes("en déplacement") ||
    snippet.includes("sabbatical")
  ) {
    status = "auto_reply";
    sentiment = null;
    notes = "auto reply - out of office or away";
  }

  // WRONG CONTACT — person left company
  else if (
    snippet.includes("ne fais plus partie") ||
    snippet.includes("no longer") ||
    snippet.includes("redirigée vers") ||
    snippet.includes("please contact")
  ) {
    status = "wrong_contact";
    sentiment = null;
    notes = "contact no longer at company";
  }

  // HUMAN REJECTION — default
  else {
    status = "replied";
    sentiment = "negative";
    notes = "human rejection";
  }

  // --- Parse From field ---
  // Handles: "First Last <email@domain.com>" and bare "email@domain.com"
  const fromRaw = email.From || "";
  const emailMatch = fromRaw.match(/<(.+?)>/);
  const senderEmail = (emailMatch ? emailMatch[1] : fromRaw)
    .toLowerCase()
    .trim();
  const senderDomain = senderEmail.split("@")[1]?.trim() || null;

  // Extract display name
  const namePart = fromRaw.includes("<")
    ? fromRaw.split("<")[0].trim().replace(/^"|"$/g, "")
    : "";

  const nameParts = namePart.split(" ").filter((p) => p.length > 0);
  let firstName = null;
  let lastName = null;

  if (nameParts.length >= 2) {
    // Handle "LASTNAME Firstname" format (first word all caps)
    if (
      nameParts[0] === nameParts[0].toUpperCase() &&
      nameParts[0].length > 1
    ) {
      lastName = nameParts[0];
      firstName = nameParts.slice(1).join(" ");
    } else {
      firstName = nameParts[0];
      lastName = nameParts.slice(1).join(" ");
    }
  } else if (nameParts.length === 1) {
    firstName = nameParts[0];
  }

  const toTitleCase = (str) =>
    str ? str.charAt(0).toUpperCase() + str.slice(1).toLowerCase() : null;

  return {
    json: {
      gmail_id: email.id,
      thread_id: email.threadId,
      from_raw: fromRaw,
      from_email: senderEmail,
      from_domain: senderDomain,
      first_name: toTitleCase(firstName),
      last_name: toTitleCase(lastName),
      subject: email.Subject,
      snippet: email.snippet,
      received_at: new Date(parseInt(email.internalDate)).toISOString(),
      detected_status: status,
      detected_sentiment: sentiment,
      notes,
    },
  };
});
