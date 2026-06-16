"""Landing Formulas — modular configuration for different landing page types.

Each formula defines:
- Which capture module to include (waitlist, contact, newsletter, booking, payment)
- Configuration for that module (ListMonk list ID, email forwarding, etc.)
- Default sections to include/exclude in the generated HTML

Formulas are injected into the landing page HTML during generation.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


# ── Formula Types ──────────────────────────────────────

class FormulaType(str, Enum):
    """Supported landing page formulas — defines the capture/integration type."""

    WAITLIST = "waitlist"
    """Email capture via ListMonk. User subscribes to a mailing list."""

    CONTACT = "contact"
    """Contact form. Messages are forwarded to an email address."""

    NEWSLETTER = "newsletter"
    """Double opt-in newsletter via ListMonk. Requires email confirmation."""

    BOOKING = "booking"
    """Schedule a demo / booking via embedded calendar (Calendly placeholder)."""

    PAYMENT = "payment"
    """Pre-order / payment via Stripe checkout link."""

    SURVEY = "survey"
    """Feedback / survey form. Responses collected via webhook or email."""


# ── Formula Configuration ──────────────────────────────

@dataclass
class FormulaConfig:
    """Configuration for a landing page formula.

    Each formula type has different required/optional configuration fields.
    The Generator uses this to inject the appropriate HTML/JS into the page.
    """

    formula: FormulaType

    # ── Common fields ──
    project_id: str = ""
    """Unique project ID used for tracking and ListMonk list creation."""

    # ── Waitlist / Newsletter (ListMonk) ──
    listmonk_url: str = ""
    """ListMonk instance URL. Falls back to global LISTMONK_URL."""
    listmonk_list_id: int = 0
    """ListMonk list ID. If 0, a new list is auto-created."""
    listmonk_api_user: str = ""
    """ListMonk API username. Falls back to global default."""
    listmonk_api_token: str = ""
    """ListMonk API token. Falls back to global default."""

    # ── Contact form ──
    contact_email: str = ""
    """Email address where contact form submissions are forwarded."""
    contact_webhook_url: str = ""
    """Optional webhook URL for contact form submissions."""

    # ── Booking ──
    booking_url: str = ""
    """URL to embedded booking tool (e.g. Calendly link)."""

    # ── Payment / Pre-order ──
    stripe_link: str = ""
    """Stripe payment link or checkout URL."""
    price_display: str = ""
    """Price to display (e.g. '$29/mo')."""

    # ── Sections to include ──
    sections: list[str] = field(default_factory=lambda: [
        "hero", "features", "how_it_works", "social_proof",
        "pricing", "faq", "cta", "capture_form",
    ])
    """Which sections to include in the landing page."""


# ── Formula Registry ───────────────────────────────────

class FormulaRegistry:
    """Registry of formula configurations and helpers."""

    @staticmethod
    def get_default_config(formula: FormulaType, project_id: str = "") -> FormulaConfig:
        """Get a default configuration for a formula type."""
        return FormulaConfig(
            formula=formula,
            project_id=project_id,
        )

    @staticmethod
    def get_capture_html(config: FormulaConfig, slug: str) -> str:
        """Generate the capture form HTML for a given formula configuration.

        Returns the HTML/JS snippet to be injected into the landing page.
        """
        form_id = f"capture-form-{slug[:20]}"

        if config.formula == FormulaType.WAITLIST:
            return FormulaRegistry._waitlist_html(config, form_id, slug)
        elif config.formula == FormulaType.NEWSLETTER:
            return FormulaRegistry._newsletter_html(config, form_id, slug)
        elif config.formula == FormulaType.CONTACT:
            return FormulaRegistry._contact_html(config, form_id, slug)
        elif config.formula == FormulaType.BOOKING:
            return FormulaRegistry._booking_html(config, form_id)
        elif config.formula == FormulaType.PAYMENT:
            return FormulaRegistry._payment_html(config, form_id)
        elif config.formula == FormulaType.SURVEY:
            return FormulaRegistry._survey_html(config, form_id, slug)
        else:
            return FormulaRegistry._waitlist_html(config, form_id, slug)

    @staticmethod
    def _waitlist_html(config: FormulaConfig, form_id: str, slug: str) -> str:
        """HTML for ListMonk waitlist capture form."""
        list_id = config.listmonk_list_id or 0
        return f"""
      <!-- CAPTURE: Waitlist (ListMonk) -->
      <section class="py-16 bg-teal-50 dark:bg-teal-500/5 border-t border-teal-200 dark:border-teal-500/10" aria-label="Waitlist">
        <div class="max-w-lg mx-auto px-6 text-center">
          <h2 class="text-2xl font-bold text-teal-800 dark:text-teal-300 mb-3 lang-en">Join the Waitlist</h2>
          <h2 class="text-2xl font-bold text-teal-800 dark:text-teal-300 mb-3 lang-es">Unete a la Lista</h2>
          <h2 class="text-2xl font-bold text-teal-800 dark:text-teal-300 mb-3 lang-de">Warteliste</h2>
          <p class="text-teal-700 dark:text-teal-400 mb-6 text-sm lang-en">Be the first to know when we launch.</p>
          <p class="text-teal-700 dark:text-teal-400 mb-6 text-sm lang-es">Se el primero en saber cuando lancemos.</p>
          <p class="text-teal-700 dark:text-teal-400 mb-6 text-sm lang-de">Erfahre als Erster vom Start.</p>
          <form id="{form_id}" class="flex gap-2 max-w-md mx-auto" onsubmit="return false">
            <input type="email" id="{form_id}-email" placeholder="you@email.com" required
              class="flex-1 px-4 py-3 rounded-xl border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-white text-sm focus:outline-none focus:border-teal-500 transition">
            <button type="submit" onclick="submitWaitlist('{form_id}', {list_id})"
              class="px-6 py-3 bg-teal-600 hover:bg-teal-500 text-white font-semibold rounded-xl text-sm transition-colors whitespace-nowrap lang-en">Subscribe</button>
            <button type="submit" onclick="submitWaitlist('{form_id}', {list_id})"
              class="px-6 py-3 bg-teal-600 hover:bg-teal-500 text-white font-semibold rounded-xl text-sm transition-colors whitespace-nowrap lang-es">Suscribirse</button>
            <button type="submit" onclick="submitWaitlist('{form_id}', {list_id})"
              class="px-6 py-3 bg-teal-600 hover:bg-teal-500 text-white font-semibold rounded-xl text-sm transition-colors whitespace-nowrap lang-de">Abonnieren</button>
          </form>
          <div id="{form_id}-status" class="mt-3 text-sm"></div>
        </div>
      </section>
      <script>
      function submitWaitlist(formId, listId) {{
        var email = document.getElementById(formId + '-email').value;
        var status = document.getElementById(formId + '-status');
        if (!email || !email.includes('@')) {{ status.textContent = 'Valid email required'; status.className = 'mt-3 text-sm text-red-500'; return; }}
        status.textContent = 'Subscribing...'; status.className = 'mt-3 text-sm text-teal-600';
        fetch('/api/waitlist/subscribe', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ email: email, name: email.split('@')[0], list_id: listId }})
        }})
        .then(function(r) {{ return r.json(); }})
        .then(function(d) {{
          if (d.success) {{
            status.innerHTML = '✅ ' + d.message; status.className = 'mt-3 text-sm text-teal-600';
            document.getElementById(formId + '-email').value = '';
          }} else {{
            status.textContent = d.message || 'Error'; status.className = 'mt-3 text-sm text-red-500';
          }}
        }})
        .catch(function() {{
          status.textContent = 'Network error'; status.className = 'mt-3 text-sm text-red-500';
        }});
      }}
      </script>"""

    @staticmethod
    def _newsletter_html(config: FormulaConfig, form_id: str, slug: str) -> str:
        """HTML for newsletter signup (similar to waitlist but labeled differently)."""
        list_id = config.listmonk_list_id or 0
        return f"""
      <!-- CAPTURE: Newsletter -->
      <section class="py-16 bg-teal-50 dark:bg-teal-500/5 border-t border-teal-200 dark:border-teal-500/10" aria-label="Newsletter">
        <div class="max-w-lg mx-auto px-6 text-center">
          <h2 class="text-2xl font-bold text-teal-800 dark:text-teal-300 mb-3 lang-en">Stay Updated</h2>
          <h2 class="text-2xl font-bold text-teal-800 dark:text-teal-300 mb-3 lang-es">Mantente Informado</h2>
          <h2 class="text-2xl font-bold text-teal-800 dark:text-teal-300 mb-3 lang-de">Bleib Informiert</h2>
          <p class="text-teal-700 dark:text-teal-400 mb-6 text-sm">Get weekly updates and early access.</p>
          <form id="{form_id}" class="flex gap-2 max-w-md mx-auto" onsubmit="return false">
            <input type="email" id="{form_id}-email" placeholder="you@email.com" required
              class="flex-1 px-4 py-3 rounded-xl border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-white text-sm focus:outline-none focus:border-teal-500 transition">
            <button type="submit" onclick="submitWaitlist('{form_id}', {list_id})"
              class="px-6 py-3 bg-teal-600 hover:bg-teal-500 text-white font-semibold rounded-xl text-sm transition-colors whitespace-nowrap">Subscribe</button>
          </form>
          <div id="{form_id}-status" class="mt-3 text-sm"></div>
        </div>
      </section>
      <script>
      function submitWaitlist(formId, listId) {{
        var email = document.getElementById(formId + '-email').value;
        var status = document.getElementById(formId + '-status');
        if (!email || !email.includes('@')) {{ status.textContent = 'Valid email required'; status.className = 'mt-3 text-sm text-red-500'; return; }}
        fetch('/api/waitlist/subscribe', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ email: email, name: email.split('@')[0], list_id: listId }})
        }})
        .then(function(r) {{ return r.json(); }})
        .then(function(d) {{
          if (d.success) {{
            status.textContent = '✅ Check your email for confirmation!'; status.className = 'mt-3 text-sm text-teal-600';
          }} else {{
            status.textContent = d.message || 'Error'; status.className = 'mt-3 text-sm text-red-500';
          }}
        }})
        .catch(function() {{ status.textContent = 'Network error'; status.className = 'mt-3 text-sm text-red-500'; }});
      }}
      </script>"""

    @staticmethod
    def _contact_html(config: FormulaConfig, form_id: str, slug: str) -> str:
        """HTML for a contact form that sends to an email/webhook."""
        return f"""
      <!-- CAPTURE: Contact Form -->
      <section class="py-16 bg-teal-50 dark:bg-teal-500/5 border-t border-teal-200 dark:border-teal-500/10" aria-label="Contact">
        <div class="max-w-lg mx-auto px-6 text-center">
          <h2 class="text-2xl font-bold text-teal-800 dark:text-teal-300 mb-3 lang-en">Get in Touch</h2>
          <h2 class="text-2xl font-bold text-teal-800 dark:text-teal-300 mb-3 lang-es">Contacto</h2>
          <h2 class="text-2xl font-bold text-teal-800 dark:text-teal-300 mb-3 lang-de">Kontakt</h2>
          <form id="{form_id}" class="text-left space-y-4 max-w-md mx-auto" onsubmit="return false">
            <input type="text" id="{form_id}-name" placeholder="Your name"
              class="w-full px-4 py-3 rounded-xl border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-white text-sm focus:outline-none focus:border-teal-500 transition">
            <input type="email" id="{form_id}-email" placeholder="your@email.com" required
              class="w-full px-4 py-3 rounded-xl border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-white text-sm focus:outline-none focus:border-teal-500 transition">
            <textarea id="{form_id}-message" rows="3" placeholder="Your message..." required
              class="w-full px-4 py-3 rounded-xl border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-white text-sm focus:outline-none focus:border-teal-500 transition"></textarea>
            <button type="submit" onclick="submitContact('{form_id}', '{config.contact_email}', '{config.contact_webhook_url}')"
              class="w-full px-6 py-3 bg-teal-600 hover:bg-teal-500 text-white font-semibold rounded-xl text-sm transition-colors lang-en">Send Message</button>
            <button type="submit" onclick="submitContact('{form_id}', '{config.contact_email}', '{config.contact_webhook_url}')"
              class="w-full px-6 py-3 bg-teal-600 hover:bg-teal-500 text-white font-semibold rounded-xl text-sm transition-colors lang-es">Enviar</button>
            <button type="submit" onclick="submitContact('{form_id}', '{config.contact_email}', '{config.contact_webhook_url}')"
              class="w-full px-6 py-3 bg-teal-600 hover:bg-teal-500 text-white font-semibold rounded-xl text-sm transition-colors lang-de">Senden</button>
          </form>
          <div id="{form_id}-status" class="mt-3 text-sm"></div>
        </div>
      </section>
      <script>
      function submitContact(formId, email, webhook) {{
        var name = document.getElementById(formId + '-name').value;
        var emailVal = document.getElementById(formId + '-email').value;
        var message = document.getElementById(formId + '-message').value;
        var status = document.getElementById(formId + '-status');
        if (!emailVal || !message) {{ status.textContent = 'Email and message required'; status.className = 'mt-3 text-sm text-red-500'; return; }}
        status.textContent = 'Sending...'; status.className = 'mt-3 text-sm text-teal-600';
        fetch('/api/contact/submit', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ name: name, email: emailVal, message: message, to: email, project: '{slug}' }})
        }})
        .then(function(r) {{ return r.json(); }})
        .then(function(d) {{
          if (d.success) {{ status.textContent = '✅ Message sent!'; status.className = 'mt-3 text-sm text-teal-600'; }}
          else {{ status.textContent = d.message || 'Error'; status.className = 'mt-3 text-sm text-red-500'; }}
        }})
        .catch(function() {{ status.textContent = 'Network error'; status.className = 'mt-3 text-sm text-red-500'; }});
      }}
      </script>"""

    @staticmethod
    def _booking_html(config: FormulaConfig, form_id: str) -> str:
        """HTML for booking/demo scheduling (Calendly-style embed)."""
        booking_url = config.booking_url or "https://calendly.com/pitchforge/demo"
        return f"""
      <!-- CAPTURE: Booking -->
      <section class="py-16 bg-teal-50 dark:bg-teal-500/5 border-t border-teal-200 dark:border-teal-500/10" aria-label="Book a demo">
        <div class="max-w-4xl mx-auto px-6 text-center">
          <h2 class="text-2xl font-bold text-teal-800 dark:text-teal-300 mb-3 lang-en">Book a Demo</h2>
          <h2 class="text-2xl font-bold text-teal-800 dark:text-teal-300 mb-3 lang-es">Agenda una Demo</h2>
          <h2 class="text-2xl font-bold text-teal-800 dark:text-teal-300 mb-3 lang-de">Demo Buchen</h2>
          <p class="text-teal-700 dark:text-teal-400 mb-6 text-sm">Schedule a 15-min call to see it in action.</p>
          <a href="{booking_url}" target="_blank" rel="noopener"
            class="inline-block px-8 py-4 bg-teal-600 hover:bg-teal-500 text-white font-semibold rounded-xl transition-colors">
            <span class="lang-en">Schedule Now</span>
            <span class="lang-es">Programar Ahora</span>
            <span class="lang-de">Jetzt Planen</span>
          </a>
        </div>
      </section>"""

    @staticmethod
    def _payment_html(config: FormulaConfig, form_id: str) -> str:
        """HTML for pre-order / payment via Stripe."""
        stripe_link = config.stripe_link or "#"
        price = config.price_display or "$29"
        return f"""
      <!-- CAPTURE: Pre-order / Payment -->
      <section class="py-16 bg-teal-50 dark:bg-teal-500/5 border-t border-teal-200 dark:border-teal-500/10" aria-label="Pre-order">
        <div class="max-w-lg mx-auto px-6 text-center">
          <h2 class="text-2xl font-bold text-teal-800 dark:text-teal-300 mb-3 lang-en">Pre-Order Now</h2>
          <h2 class="text-2xl font-bold text-teal-800 dark:text-teal-300 mb-3 lang-es">Pre-Ordenar</h2>
          <h2 class="text-2xl font-bold text-teal-800 dark:text-teal-300 mb-3 lang-de">Vorbestellen</h2>
          <p class="text-3xl font-bold text-teal-600 dark:text-teal-400 mb-4">{price}</p>
          <p class="text-teal-700 dark:text-teal-400 mb-6 text-sm">Secure payment via Stripe. Cancel anytime.</p>
          <a href="{stripe_link}" target="_blank" rel="noopener"
            class="inline-block px-8 py-4 bg-teal-600 hover:bg-teal-500 text-white font-semibold rounded-xl transition-colors">
            <span class="lang-en">Pre-Order</span>
            <span class="lang-es">Pre-Ordenar</span>
            <span class="lang-de">Vorbestellen</span>
          </a>
        </div>
      </section>"""

    @staticmethod
    def _survey_html(config: FormulaConfig, form_id: str, slug: str) -> str:
        """HTML for a feedback/survey form."""
        return f"""
      <!-- CAPTURE: Survey -->
      <section class="py-16 bg-teal-50 dark:bg-teal-500/5 border-t border-teal-200 dark:border-teal-500/10" aria-label="Feedback">
        <div class="max-w-lg mx-auto px-6 text-center">
          <h2 class="text-2xl font-bold text-teal-800 dark:text-teal-300 mb-3 lang-en">Share Your Feedback</h2>
          <h2 class="text-2xl font-bold text-teal-800 dark:text-teal-300 mb-3 lang-es">Comparte tu Opinion</h2>
          <h2 class="text-2xl font-bold text-teal-800 dark:text-teal-300 mb-3 lang-de">Feedback Geben</h2>
          <form id="{form_id}" class="text-left space-y-4 max-w-md mx-auto" onsubmit="return false">
            <textarea id="{form_id}-feedback" rows="3" placeholder="Your feedback..." required
              class="w-full px-4 py-3 rounded-xl border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-white text-sm focus:outline-none focus:border-teal-500 transition"></textarea>
            <input type="email" id="{form_id}-email" placeholder="your@email.com (optional)"
              class="w-full px-4 py-3 rounded-xl border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-white text-sm focus:outline-none focus:border-teal-500 transition">
            <button type="submit" onclick="submitSurvey('{form_id}', '{slug}')"
              class="w-full px-6 py-3 bg-teal-600 hover:bg-teal-500 text-white font-semibold rounded-xl text-sm transition-colors">Submit</button>
          </form>
          <div id="{form_id}-status" class="mt-3 text-sm"></div>
        </div>
      </section>
      <script>
      function submitSurvey(formId, project) {{
        var feedback = document.getElementById(formId + '-feedback').value;
        var email = document.getElementById(formId + '-email').value;
        var status = document.getElementById(formId + '-status');
        if (!feedback) {{ status.textContent = 'Please enter your feedback'; status.className = 'mt-3 text-sm text-red-500'; return; }}
        status.textContent = 'Submitting...'; status.className = 'mt-3 text-sm text-teal-600';
        fetch('/api/survey/submit', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ feedback: feedback, email: email, project: project }})
        }})
        .then(function(r) {{ return r.json(); }})
        .then(function(d) {{
          if (d.success) {{ status.textContent = '✅ Thank you!'; status.className = 'mt-3 text-sm text-teal-600'; }}
          else {{ status.textContent = d.message || 'Error'; status.className = 'mt-3 text-sm text-red-500'; }}
        }})
        .catch(function() {{ status.textContent = 'Network error'; status.className = 'mt-3 text-sm text-red-500'; }});
      }}
      </script>"""

