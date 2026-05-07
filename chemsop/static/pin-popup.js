// Simple PIN popup system - minimal JavaScript for PIN verification only

function showPinPopup(options) {
  const { 
    title = 'Enter PIN', 
    message = 'Please enter your PIN to continue',
    onVerify,
    requireOwner = false,
    sopOwnerId = null
  } = options;
  
  // Create overlay
  const overlay = document.createElement('div');
  overlay.id = 'pin-overlay';
  overlay.style.cssText = `
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    justify-content: center;
    align-items: center;
    z-index: 10000;
  `;
  
  // Create popup
  const popup = document.createElement('div');
  popup.style.cssText = `
    background: white;
    padding: 30px;
    border: 3px solid black;
    border-radius: 8px;
    max-width: 400px;
    width: 90%;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
  `;
  
  popup.innerHTML = `
    <h2 style="margin-top: 0; font-size: 24px; text-align: center;">${title}</h2>
    <p style="text-align: center; color: #666; margin-bottom: 20px;">${message}</p>
    <form id="pin-form">
      <div style="margin-bottom: 20px;">
        <label style="display: block; margin-bottom: 8px; font-weight: bold;">PIN:</label>
        <input 
          type="password" 
          id="pin-input" 
          minlength="6" 
          required 
          style="width: 100%; padding: 10px; border: 2px solid black; border-radius: 5px; font-size: 16px; box-sizing: border-box;"
          autofocus
        >
      </div>
      <div id="pin-error" style="color: #dc3545; margin-bottom: 15px; text-align: center; display: none;"></div>
      <div style="display: flex; gap: 10px;">
        <button 
          type="button" 
          id="pin-cancel" 
          style="flex: 1; padding: 12px; background: white; color: black; border: 2px solid black; border-radius: 5px; cursor: pointer; font-size: 16px; font-weight: 600;"
        >Cancel</button>
        <button 
          type="submit" 
          style="flex: 1; padding: 12px; background: black; color: white; border: 2px solid black; border-radius: 5px; cursor: pointer; font-size: 16px; font-weight: 600;"
        >Verify</button>
      </div>
    </form>
  `;
  
  overlay.appendChild(popup);
  document.body.appendChild(overlay);
  document.getElementById('pin-input').focus();
  
  // Handle ESC key
  function handleEsc(e) {
    if (e.key === 'Escape') {
      closePinPopup();
    }
  }
  document.addEventListener('keydown', handleEsc);
  
  function closePinPopup() {
    document.removeEventListener('keydown', handleEsc);
    overlay.remove();
  }
  
  // Cancel button
  document.getElementById('pin-cancel').onclick = closePinPopup;
  
  // Form submission
  document.getElementById('pin-form').onsubmit = async function(e) {
    e.preventDefault();
    const pin = document.getElementById('pin-input').value;
    const errorDiv = document.getElementById('pin-error');
    
    try {
      // Verify PIN via callback
      const result = await onVerify(pin);
      
      if (result.success) {
        closePinPopup();
      } else {
        errorDiv.textContent = result.error || 'Invalid PIN';
        errorDiv.style.display = 'block';
        document.getElementById('pin-input').value = '';
        document.getElementById('pin-input').focus();
      }
    } catch (error) {
      errorDiv.textContent = 'Verification failed. Please try again.';
      errorDiv.style.display = 'block';
    }
  };
}

// Verify PIN against owner for edit access
async function verifyOwnerPin(sopId, pin) {
  try {
    const response = await fetch('/verify-owner-pin', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ sop_id: sopId, pin: pin })
    });
    
    const data = await response.json();
    return data;
  } catch (error) {
    return { success: false, error: 'Network error' };
  }
}

// Show edit PIN popup when accessing draft
function requireEditPin(sopId, onSuccess) {
  showPinPopup({
    title: 'Owner Verification',
    message: 'Only the SOP owner can edit this draft',
    onVerify: async (pin) => {
      const result = await verifyOwnerPin(sopId, pin);
      if (result.success) {
        onSuccess();
      }
      return result;
    }
  });
}

// Submit SOP for approval with PIN verification
function submitSopForApproval(sopId) {
  // Collect form data
  const title = document.getElementById('title').value;
  const course = document.getElementById('course').value;
  const ownerId = document.getElementById('ownerId').value;
  const versionType = document.querySelector('input[name="versionType"]:checked')?.value;
  
  if (!versionType) {
    alert('Please select whether this is a major or minor change');
    return;
  }
  
  // Collect sections - now building markdown from sections
  const sections = {};
  const sectionNames = ['Lab Description', 'Reagent list', 'Chemicals to prepare', 'Laboratory setup', 'Waste streams'];
  
  for (const sectionName of sectionNames) {
    const sectionId = 'section_' + sectionName.replace(/ /g, '_');
    const textarea = document.getElementById(sectionId);
    if (textarea) {
      sections[sectionName] = textarea.value.trim();
    }
  }
  
  // Build markdown from sections
  let procedure = '# ' + title + '\n\n';
  for (const sectionName of sectionNames) {
    procedure += '## ' + sectionName + '\n\n';
    if (sections[sectionName]) {
      procedure += sections[sectionName] + '\n\n';
    }
  }
  
  // Check if major change and faculty reviewer is required
  let facultyReviewerId = null;
  
  showPinPopup({
    title: 'Submit for Approval',
    message: 'Enter your PIN to submit this SOP for approval',
    onVerify: async (pin) => {
      try {
        const response = await fetch('/submit-sop', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ 
            sop_id: sopId, 
            pin: pin,
            title: title,
            course: course,
            ownerId: ownerId,
            procedure: procedure,
            versionType: versionType,
            facultyReviewerId: facultyReviewerId
          })
        });
        
        const data = await response.json();
        
        if (data.success) {
          // Redirect to SOPs page on success
          window.location.href = '/sops';
        }
        
        return data;
      } catch (error) {
        return { success: false, error: 'Submission failed. Please try again.' };
      }
    }
  });
}

// Approve SOP with PIN verification
function approveSop(sopId, comment) {
  showPinPopup({
    title: 'Approve SOP',
    message: 'Enter your PIN to approve this SOP',
    onVerify: async (pin) => {
      try {
        const response = await fetch('/approve-sop', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ sop_id: sopId, pin: pin, comment: comment })
        });
        
        const data = await response.json();
        
        if (data.success) {
          window.location.href = '/sops';
        }
        
        return data;
      } catch (error) {
        return { success: false, error: 'Approval failed. Please try again.' };
      }
    }
  });
}

// Send back SOP with PIN verification
function sendBackSop(sopId, comment) {
  showPinPopup({
    title: 'Send Back SOP',
    message: 'Enter your PIN to send this SOP back to the owner',
    onVerify: async (pin) => {
      try {
        const response = await fetch('/send-back-sop', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ sop_id: sopId, pin: pin, comment: comment })
        });
        
        const data = await response.json();
        
        if (data.success) {
          window.location.href = '/sops';
        }
        
        return data;
      } catch (error) {
        return { success: false, error: 'Send back failed. Please try again.' };
      }
    }
  });
}

// Pull back SOP with PIN verification
function pullBackSop(sopId) {
  showPinPopup({
    title: 'Pull Back to Draft',
    message: 'Enter your PIN to pull this SOP back to draft status',
    onVerify: async (pin) => {
      try {
        const response = await fetch('/pull-back-sop', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ sop_id: sopId, pin: pin })
        });
        
        const data = await response.json();
        
        if (data.success) {
          window.location.href = '/sops';
        }
        
        return data;
      } catch (error) {
        return { success: false, error: 'Pull back failed. Please try again.' };
      }
    }
  });
}

// Mark SOP as reviewed by faculty with PIN verification
function markSopReviewed(sopId) {
  showPinPopup({
    title: 'Mark as Reviewed',
    message: 'Enter your PIN to mark this SOP as reviewed',
    onVerify: async (pin) => {
      try {
        const response = await fetch('/mark-sop-reviewed', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ sop_id: sopId, pin: pin })
        });
        
        const data = await response.json();
        
        if (data.success) {
          window.location.reload();
        }
        
        return data;
      } catch (error) {
        return { success: false, error: 'Review marking failed. Please try again.' };
      }
    }
  });
}

// Discard draft SOP with confirmation only (already PIN verified to access page)
function discardDraftSop(sopId) {
  if (!confirm('Are you sure you want to discard this draft? This action cannot be undone.')) {
    return;
  }
  
  fetch('/discard-draft-sop', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ sop_id: sopId })
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      window.location.href = '/sops';
    } else {
      alert('Error: ' + (data.error || 'Discard failed. Please try again.'));
    }
  })
  .catch(error => {
    alert('Error: Discard failed. Please try again.');
  });
}

// Transfer SOP ownership with PIN verification
function transferSopOwnership(sopId, newOwnerId, newOwnerName, callback) {
  if (!confirm('⚠️ WARNING: Transferring ownership will remove your access to this SOP.\n\nThe new owner will be: ' + newOwnerName + '\n\nYou will not be able to edit this SOP after the transfer.\n\nAre you sure you want to continue?')) {
    if (callback) callback(false);
    return;
  }
  
  showPinPopup({
    title: 'Transfer Ownership',
    message: 'Enter your PIN to confirm ownership transfer',
    onVerify: async (pin) => {
      try {
        console.log('Sending ownership transfer request:', { sop_id: sopId, new_owner_id: newOwnerId });
        const response = await fetch('/transfer-sop-ownership', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ 
            sop_id: sopId,
            new_owner_id: newOwnerId,
            pin: pin
          })
        });
        
        console.log('Response status:', response.status);
        const data = await response.json();
        console.log('Response data:', data);
        
        if (data.success) {
          window.location.href = '/sops';
          if (callback) callback(true);
        } else {
          if (callback) callback(false);
        }
        
        return data;
      } catch (error) {
        console.error('Transfer error:', error);
        if (callback) callback(false);
        return { success: false, error: 'Ownership transfer failed. Please try again.' };
      }
    }
  });
}
