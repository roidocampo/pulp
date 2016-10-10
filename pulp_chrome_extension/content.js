var citation_title = $('meta[name=citation_title]').attr("content");

console.log("ArXiv title:", citation_title);

var search_query = encodeURIComponent(citation_title);

function get_JSON(json_url, callback) {
    chrome.runtime.sendMessage({
        method: 'GET',
        action: 'xhttp',
        url: json_url,
        data: ''
    }, function(responseText) {
        var data = JSON.parse(responseText);
        callback(data);
    })
}

get_JSON("http://localhost:23232/search?" + search_query, function(data) {
    console.log("Pulp Search:");
    console.log(data);
    if ($.isArray(data) && data.length > 0) {
        var file = data[0];
        var li_html  = 
            "<li>"
            + "<a class='open_in_pulp' href='#'>"
            + "Open in Pulp"
            + "</a>"
            + "</li>"
            ;
        $(".full-text ul").prepend( $(li_html) );
        $(".open_in_pulp").on("click", function (){
            get_JSON("http://localhost:23232/open?" + file, function(data) {
                console.log("Opened: " + file);
            });
        });
    };
});
