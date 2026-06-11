import React, { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";

const TOUR_STEPS = [
  {
    title: "Welcome to RecoverFlow AI! 🚀",
    body: "Ready to recover up to 15% of your lost sales? Take a 1-minute quick tour to see how the dashboard works, or skip it to get started right away.",
    targetId: null,
    isCentered: true,
    illustration: "👋",
  },
  {
    title: "Real-Time ROI Metrics",
    body: "Track your recovered revenue, recovery rate, and total recovered orders here. RecoverFlow updates these metrics in real-time as sales come in.",
    targetId: "tour-roi",
    isCentered: false,
  },
  {
    title: "Credits Wallet",
    body: "Keep track of your WhatsApp credits. One credit is used per recovery message sent. You can recharge your balance anytime.",
    targetId: "tour-credits",
    isCentered: false,
  },
  {
    title: "RecoverFlow AI Assistant",
    body: "Need help connecting your Meta WhatsApp API or selecting a brand tone? Ask our RAG-powered AI chatbot for instant support.",
    targetId: "tour-chatbot",
    isCentered: false,
  },
  {
    title: "Abandoned Carts & Reminder Logs",
    body: "Monitor recent cart drop-offs, AI customer segments (like VIP or First-Time), and detailed delivery logs of sent messages here.",
    targetId: "tour-logs",
    isCentered: false,
  },
  {
    title: "You're Ready to Recover! 🎉",
    body: "The tour is complete! Head over to Settings to configure your brand voice and connect WhatsApp to launch your campaigns.",
    targetId: null,
    isCentered: true,
    illustration: "🥳",
  },
];

export default function OnboardingTour() {
  const [stepIndex, setStepIndex] = useState(-1);
  const [coords, setCoords] = useState({ top: 0, left: 0 });
  const [mounted, setMounted] = useState(false);
  const activeElementRef = useRef(null);

  useEffect(() => {
    setMounted(true);
    // Check if the user has completed the tour already
    const isCompleted = localStorage.getItem("rf_tour_completed");
    if (!isCompleted) {
      setStepIndex(0); // Start the tour
    }
  }, []);

  const currentStep = stepIndex >= 0 && stepIndex < TOUR_STEPS.length ? TOUR_STEPS[stepIndex] : null;

  // Update spotlight and coordinates
  useEffect(() => {
    // Clean up previous spotlight class & style
    if (activeElementRef.current) {
      const { element, originalPosition } = activeElementRef.current;
      if (element) {
        element.classList.remove("rf-tour-spotlight-active");
        element.style.position = originalPosition;
      }
      activeElementRef.current = null;
    }

    if (!currentStep) return;

    const updatePosition = () => {
      try {
        if (currentStep.isCentered || !currentStep.targetId) {
          setCoords({ top: 0, left: 0 });
          return;
        }

        const element = document.getElementById(currentStep.targetId);
        if (!element) {
          // Fallback to centered if element not found in DOM
          setCoords({ top: 0, left: 0 });
          return;
        }

        // Preserve positioning for fixed/absolute elements
        const originalPos = element.style.position;
        const computedPos = window.getComputedStyle(element).position;
        if (computedPos === "static") {
          element.style.position = "relative";
        }

        // Add spotlight effect class to highlight the element
        element.classList.add("rf-tour-spotlight-active");
        activeElementRef.current = { element, originalPosition: originalPos };

        const rect = element.getBoundingClientRect();
        
        // If element is completely hidden or zero-sized, fall back to center
        if (rect.width === 0 || rect.height === 0) {
          setCoords({ top: 0, left: 0 });
          return;
        }

        const viewportHeight = window.innerHeight;
        const viewportWidth = window.innerWidth;

        let top = 0;
        let left = 0;

        if (currentStep.targetId === "tour-chatbot") {
          // Place to the left of the chatbot button to avoid vertical overlap
          left = rect.left + window.scrollX - 336;
          top = rect.top + window.scrollY - 80;
        } else {
          // Default: place below the element
          top = rect.bottom + window.scrollY + 16;
          left = rect.left + window.scrollX + (rect.width / 2) - 160; // center tooltip horizontally

          // Adjust if tooltip overflows viewport bottom
          if (top + 200 > viewportHeight + window.scrollY) {
            // Place above the element
            top = rect.top + window.scrollY - 220; // increased spacing to avoid overlapping the element top boundary
          }
        }

        // Adjust if tooltip overflows viewport left/right
        if (left < 16) {
          left = 16;
        } else if (left + 320 > viewportWidth + window.scrollX) {
          left = viewportWidth + window.scrollX - 336;
        }

        // Adjust if tooltip overflows viewport bottom/top
        const cardEstimatedHeight = 240;
        if (top + cardEstimatedHeight > viewportHeight + window.scrollY) {
          top = viewportHeight + window.scrollY - cardEstimatedHeight - 16;
        }
        if (top < window.scrollY + 16) {
          top = window.scrollY + 16;
        }

        if (isNaN(top) || isNaN(left)) {
          setCoords({ top: 0, left: 0 });
        } else {
          setCoords({ top, left });
        }
      } catch (err) {
        console.error("Error positioning onboarding tour card:", err);
        setCoords({ top: 0, left: 0 });
      }
    };

    updatePosition();

    // Listeners to recalculate positions dynamically
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition);

    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition);
      if (activeElementRef.current) {
        const { element, originalPosition } = activeElementRef.current;
        if (element) {
          element.classList.remove("rf-tour-spotlight-active");
          element.style.position = originalPosition;
        }
      }
    };
  }, [stepIndex, currentStep]);

  const handleNext = () => {
    if (stepIndex < TOUR_STEPS.length - 1) {
      setStepIndex(stepIndex + 1);
    } else {
      handleComplete();
    }
  };

  const handleBack = () => {
    if (stepIndex > 0) {
      setStepIndex(stepIndex - 1);
    }
  };

  const handleComplete = () => {
    localStorage.setItem("rf_tour_completed", "true");
    setStepIndex(-1);
  };

  if (!mounted || !currentStep) return null;

  return createPortal(
    <>
      {/* Semi-transparent dark background overlay */}
      <div className="rf-tour-overlay" onClick={handleComplete} />

      {/* Floating Tooltip Card */}
      <div
        className={`rf-tour-tooltip-card ${currentStep.isCentered || coords.top === 0 ? "centered" : ""}`}
        style={
          currentStep.isCentered || coords.top === 0
            ? {}
            : { top: `${coords.top}px`, left: `${coords.left}px` }
        }
      >
        <div className="rf-tour-header">
          <span className="rf-tour-step-indicator">
            Step {stepIndex + 1} of {TOUR_STEPS.length}
          </span>
          <button className="rf-tour-skip-btn" onClick={handleComplete}>
            Skip Tour
          </button>
        </div>

        {currentStep.illustration && (
          <div className="rf-tour-welcome-illustration">{currentStep.illustration}</div>
        )}

        <div className="rf-tour-title">{currentStep.title}</div>
        <div className="rf-tour-body">{currentStep.body}</div>

        <div className="rf-tour-footer">
          {stepIndex > 0 && (
            <button className="rf-tour-btn secondary" onClick={handleBack}>
              Back
            </button>
          )}
          <button className="rf-tour-btn primary" onClick={handleNext}>
            {stepIndex === TOUR_STEPS.length - 1 ? "Get Started" : "Next"}
          </button>
        </div>
      </div>
    </>,
    document.body
  );
}
