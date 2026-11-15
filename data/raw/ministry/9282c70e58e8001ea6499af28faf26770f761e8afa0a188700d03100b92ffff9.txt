var pricesCtrl = new function(){
	var pricesAjaxFile = $("#hdnRootFldr").val() + "ajax/pricesCtrl.php" ;
	
	this.loadPrices = function(page, args){	
		var holder = "#divPricesFilter" ;
		var enablePushState = (args !== undefined) ? args.pushState : false ;
		
		var priceTypeId = getValue(holder + " #hdnPriceTypeId")
		var fromDate = getValue(holder + " #txtFromDate") ;
		var toDate = getValue(holder + " #txtToDate") ;
		
		var dataToPost = {"action":"RenderPrices", "priceTypeId": priceTypeId, "page": page, "fromDate": fromDate, "toDate":toDate} ;	
		//console.log(dataToPost) ;
		
		$("#divPrices").append("<div class='loader'></div>") ;
	
		$.ajax({
			type: "POST",
			dataType: "json",
			url: pricesAjaxFile,
			data:  dataToPost,
			success: function(data) {
				//console.log(data) ;
					
				$("#divPrices").html(data.html) ;				           
                
            	if (window.history && window.history.pushState && enablePushState) {    
            		args.page = page ;
    	            history.pushState(args, null, data.url);    	            
            	}
			}
		});				
	} ;	
	
}