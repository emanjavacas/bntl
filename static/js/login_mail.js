
$(document).ready(function(){

    function registerError(msg) {
        $('#feedback').text(msg).addClass("text-danger");
        $('#card').addClass('border-danger');
    }

    function toggleSubmitButton(inputSelector, buttonSelector) {
        const value = $(inputSelector).val();
        $(buttonSelector).prop('disabled', !(value));
    }

    $('#mail').on('input', function() { toggleSubmitButton('#mail', '#mail-button'); });
    $('#code').on('input', function() { toggleSubmitButton('#code', '#code-button'); });

    $('#mail-form').submit(function(event) {
        event.preventDefault();

        $('#loadingModal').modal("show");

        const mail = $('#mail').val();

        $.ajax({
            type: 'POST',
            url: '/login',
            data: JSON.stringify({"mail": mail}),
            contentType: 'application/json',
            xhrFields: { withCredentials: true },
            success: function(response) {
                $('#loadingModal').modal("hide");
                if (response.next_step === "code") {
                    $('#mail-step').hide();
                    $('#code-step').show();
                    $('#masked-mail').text(mail);
                } else {
                    registerError("Unexpected response.");
                }
            },
            error: function(resp) {
                $('#loadingModal').modal("hide");
                resp = JSON.parse(resp.responseText);
                registerError(resp.detail);
            }
        });
    });

    $("#code-form").submit(function(event) {
        event.preventDefault();

        $('#loadingModal').modal("show");

        const code = $('#code').val();
        const nextUrl = new URLSearchParams(window.location.search).get('next_url') || '/';

        $.ajax({
            type: 'POST',
            url: '/login',
            data: JSON.stringify({"code": code, "next_url": nextUrl}),
            contentType: 'application/json',
            xhrFields: { withCredentials: true },
            success: function(response) {
                $('#loadingModal').modal("hide");
                if (response.status_code === 303) {
                    window.location.href = nextUrl;
                } else {
                    registerError("Unknown response.");
                }
            },
            error: function(resp) {
                $('#loadingModal').modal("hide");
                resp = JSON.parse(resp.responseText);
                registerError(resp.detail);
            }
        });
    });
});